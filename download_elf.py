#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "requests<3",
# ]
# ///

"""FactorDB/mersenne.ca aliquot sequence downloader.

This script downloads an ELF file for an aliquot sequence from FactorDB or mersenne.ca.
"""

import argparse
import configparser
import http.cookiejar
import itertools
import re
import subprocess
import sys
import time
from typing import Optional

import requests


def main() -> int:
    args = parse_args()
    if args.use_factordb:
        ElfDownloaderClass = FactorDBElfDownloader
    else:
        ElfDownloaderClass = MersenneCAElfDownloader
    elf_downloader = ElfDownloaderClass(args.sequence_base, args.expected_length, args.validation_attempts)
    try:
        elf_downloader.download_and_write_elf(f'alq_{args.sequence_base}.elf')
    except RuntimeError as error:
        if ElfDownloaderClass == MersenneCAElfDownloader:
            print(f'Could not download ELF file from mersenne.ca: {error}.')
            print('Attempting to download from FactorDB instead.')
            elf_downloader = FactorDBElfDownloader(args.sequence_base, args.expected_length, args.validation_attempts)
            elf_downloader.download_and_write_elf(f'alq_{args.sequence_base}.elf')
        else:
            raise RuntimeError('Failed to download from FactorDB') from error
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FactorDB/mersenne.ca aliquot sequence downloader")
    parser.add_argument(
        "sequence_base",
        type=str,
        help="The starting value of the sequence.",
    )
    parser.add_argument(
        "--expected-length",
        type=int,
        default=None,
        help="The expected length of the sequence. If the sequence is shorter, this script will try alternative download techniques until it matches.",
    )
    parser.add_argument(
        "--validation-attempts",
        type=int,
        default=3,
        help="The maximum number of attempts allowed to validate a sequence before the script will fail. Requires aliqueit to be configured.",
    )
    parser.add_argument(
        "--use-factordb",
        action='store_true',
        default=False,
        help="Use FactorDB instead of the cached files on mersenne.ca. FactorDB may be less reliable, but the data will always be current.",
    )
    return parser.parse_args()


class ElfDownloader:
    def __init__(self, sequence_base: str, expected_length: int, validation_attempts: int):
        self.sequence_base = sequence_base
        self.expected_length = expected_length
        self.validation_attempts = validation_attempts
        self.config = self._get_config()

    def download_and_write_elf(self, filename: str) -> None:
        for i in range(self.validation_attempts):
            self.download_elf()
            returncode = self.write_elf(filename)
            if returncode == 0:
                return
        print(f'Failed to validate ELF file after {self.validation_attempts} attempts, stopping...', file=sys.stderr)

    def download_elf(self) -> list[tuple[int, str]]:
        raise NotImplementedError()

    def write_elf(self, filename: str) -> int:
        if not self.elf_contents:
            print('ELF file is empty, cannot validate...', file=sys.stderr)
            return 1
        with open(filename, 'wt') as elf_file:
            for i, line in enumerate(self.elf_contents):
                print(f'{i} .   {line[0]} = {line[1]}', file=elf_file)
        if self.config.has_option('Programs', 'aliqueit'):
            print('aliqueit is configured, validating ELF file...')
            process = subprocess.run([self.config['Programs']['aliqueit'], '-t', self.sequence_base])
            if process.returncode == 0:
                print('ELF file validation succeeded.')
            else:
                print('ELF file validation failed.', file=sys.stderr)
            return process.returncode
        else:
            print('aliqueit is not configured, skipping validation...')
            return 0

    @staticmethod
    def parse_elf_line(elf_line: str) -> tuple[int, Optional[str]]:
        elf_line_format = r'^\d+ \.\s+(\d+) = (\d+(?:\^\d+)?(?: \* \d+(?:\^\d+)?)*)?$'
        match = re.match(elf_line_format, elf_line)
        if match:
            return (int(match[1]), match[2])
        else:
            return (0, 0)

    def _get_config(self) -> Optional[configparser.ConfigParser]:
        config = configparser.ConfigParser()
        config.read('factordb_user.ini')
        if config.sections():
            return config
        else:
            return None


class FactorDBElfDownloader(ElfDownloader):
    def __init__(self, sequence_base: str, expected_length: int, validation_attempts: int):
        super().__init__(sequence_base, expected_length, validation_attempts)
        self.cookies = self._get_cookies()
        self.elf_contents = []

    def download_elf(self) -> list[tuple[int, str]]:
        print('Downloading from FactorDB...')
        if self.expected_length is None:
            self._slice_end = None
            return self._actually_download_elf()
        self._slice_end = -1
        while len(self.elf_contents) < self.expected_length + 1:
            print(f'Download attempt {-self._slice_end}.')
            self._actually_download_elf()
            self._slice_end -= 1
        return self.elf_contents

    def _actually_download_elf(self) -> list[tuple[int, str]]:
        self.elf_contents = []
        base = self.sequence_base
        incomplete = True
        first_run = True
        already_exceeded = False
        cycle = False
        while incomplete:
            params = {'seq': base}
            temp_elf_contents = []
            try:
                with requests.get('https://factordb.com/elf.php', params=params, stream=True, cookies=self.cookies) as r:
                    line_count = 0
                    first_line = True
                    bad_file = False
                    for line in r.iter_lines(decode_unicode=True):
                        if 'html' in line:
                            bad_file = True
                            break
                        if first_line and not first_run:
                            first_line = False
                            continue
                        line_count += 1
                        parsed_line = ElfDownloader.parse_elf_line(line)
                        if not parsed_line[1]:
                            break
                        if parsed_line in self.elf_contents or parsed_line in temp_elf_contents:
                            cycle = True
                            temp_elf_contents.append(parsed_line)
                            break
                        temp_elf_contents.append(parsed_line)
                    incomplete = (bad_file or line_count > 0) and not cycle
            except requests.exceptions.ChunkedEncodingError:
                pass
            if temp_elf_contents:
                temp_max = max(map(lambda x: x[0], temp_elf_contents))
                if temp_max < 1e199 or already_exceeded:
                    self.elf_contents.extend(temp_elf_contents)
                elif self._slice_end is None:
                    raise RuntimeError('Expected length required for sequences exceeding 200 digits')
                else:
                    self.elf_contents.extend(tuple(itertools.takewhile(lambda x: x[0] < 1e199, temp_elf_contents))[0:self._slice_end])
                    already_exceeded = True
                base = self.elf_contents[-1][0]
            if bad_file:
                print('Download error, sleeping 5 seconds...')
                time.sleep(5)
            else:
                first_run = False
                size = max(0, len(self.elf_contents) - 1)
                print(f'Now at {size} lines.')
        return self.elf_contents

    def _get_cookies(self) -> Optional[http.cookiejar.CookieJar]:
        if not self.config:
            print('Running anonymously.')
            return requests.cookies.cookiejar_from_dict(dict())
        login_info = self.config['Account']

        user = login_info['User']
        if self.config.has_option('Account', 'Cookie'):
            print(f'Logged in as {user} using existing cookie.')
            return requests.cookies.cookiejar_from_dict({'fdbuser': login_info['Cookie']})

        params = {
            'user': user,
            'pass': login_info['Password'],
            'dlogin': 'Login',
        }

        r = requests.post('https://factordb.com/login.php', params)

        while not r.cookies.get('fdbuser'):
            print('Login error, sleeping 5 seconds...')
            time.sleep(5)
            r = requests.post('https://factordb.com/login.php', params)
            while r.status_code != 200:
                print('Login error, sleeping 5 seconds...')
                time.sleep(5)
                r = requests.post('https://factordb.com/login.php', params)

        print(f'Logged in as {user}.')

        login_info['Cookie'] = r.cookies.get('fdbuser')

        with open('factordb_user.ini', 'wt') as config_file:
            self.config.write(config_file)

        return r.cookies


class MersenneCAElfDownloader(ElfDownloader):
    def download_elf(self) -> list[tuple[int, str]]:
        print('Downloading from mersenne.ca...')
        with requests.get(f'https://www.mersenne.ca/factordb/elf/alq_{self.sequence_base}.elf') as r:
            if not r.ok:
                raise RuntimeError('ELF file not found on mersenne.ca')
            lines = r.text.splitlines()
            self.elf_contents = list(map(ElfDownloader.parse_elf_line, lines))
            line_count = max(0, len(self.elf_contents) - 1)
            if len(lines) != len(self.elf_contents):
                raise RuntimeError('ELF file from mersenne.ca has invalid lines')
            print(f'Downloaded {line_count} lines from mersenne.ca.')
            return self.elf_contents


if __name__ == "__main__":
    sys.exit(main())
