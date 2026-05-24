#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "requests<3",
# ]
# ///

"""FactorDB aliquot sequence downloader.

This script downloads an ELF file for an aliquot sequence from FactorDB.
"""

import argparse
import configparser
import http.cookiejar
import itertools
import re
import sys
import time
from typing import Optional

import requests


def main() -> int:
    args = parse_args()
    sequence_base = args.sequence_base
    expected_length = args.expected_length
    elf_downloader = ElfDownloader(sequence_base, expected_length)
    elf_downloader.download_and_write_elf(f'alq_{sequence_base}.elf')
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FactorDB aliquot sequence downloader")
    parser.add_argument(
        "sequence_base",
        type=str,
        help="The starting value of the sequence.",
    )
    parser.add_argument(
        "--expected-length",
        type=int,
        default=None,
        help="Provide the expected length of the sequence. If the sequence is shorter, this script will try alternative download techniques until it matches.",
    )
    return parser.parse_args()


class ElfDownloader:
    def __init__(self, sequence_base: str, expected_length: int):
        self.sequence_base = sequence_base
        self.expected_length = expected_length
        self.cookies = self._get_cookies()
        self.elf_contents = []

    def download_and_write_elf(self, filename: str) -> None:
        self.download_elf()
        self.write_elf(filename)

    def download_elf(self) -> list[tuple[int, str]]:
        if self.expected_length is None:
            self._slice_end = None
            return self._actually_download_elf()
        self._slice_end = -1
        while len(self.elf_contents) < self.expected_length + 1:
            print(f'Download attempt {-self._slice_end}.')
            self._actually_download_elf()
            self._slice_end -= 1
        return self.elf_contents

    def write_elf(self, filename: str) -> None:
        with open(filename, 'wt') as elf_file:
            for i, line in enumerate(self.elf_contents):
                print(f'{i} .   {line[0]} = {line[1]}', file=elf_file)

    def _actually_download_elf(self) -> list[tuple[int, str]]:
        self.elf_contents = []
        base = self.sequence_base
        incomplete = True
        first_run = True
        already_exceeded = False
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
                        parsed_line = self._parse_elf_line(line)
                        if not parsed_line[1]:
                            if not incomplete:
                                temp_elf_contents.append((parsed_line[0], ''))
                            break
                        temp_elf_contents.append(parsed_line)
                    incomplete = bad_file or line_count > 0
            except requests.exceptions.ChunkedEncodingError:
                pass
            if temp_elf_contents:
                temp_max = max(map(lambda x: x[0], temp_elf_contents))
                if temp_max < 1e199 or already_exceeded:
                    self.elf_contents.extend(temp_elf_contents)
                else:
                    self.elf_contents.extend(tuple(itertools.takewhile(lambda x: x[0] < 1e199, temp_elf_contents))[0:self._slice_end])
                    already_exceeded = True
                base = self.elf_contents[-1][0]
            if bad_file:
                print('Download error, sleeping 5 seconds...')
                time.sleep(5)
            else:
                first_run = False
                size = len(self.elf_contents) - 1
                print(f'Now at {size} lines.')
        return self.elf_contents

    def _get_cookies(self) -> Optional[http.cookiejar.CookieJar]:
        login_info = self._get_login()
        if not login_info:
            print('Running anonymously.')
            return requests.cookies.cookiejar_from_dict(dict())

        user = login_info['User']
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

        return r.cookies

    def _get_login(self) -> Optional[dict]:
        config = configparser.ConfigParser()
        config.read('factordb_user.ini')
        if config.has_section('Account'):
            return config['Account']
        else:
            return None

    def _parse_elf_line(self, elf_line: str) -> tuple[int, Optional[str]]:
        elf_line_format = r'^\d+ \.\s+(\d+) = (\d+(?:\^\d+)?(?: \* \d+(?:\^\d+)?)*)?$'
        match = re.match(elf_line_format, elf_line)
        if match:
            return (int(match[1]), match[2])
        else:
            return (0, 0)


if __name__ == "__main__":
    sys.exit(main())
