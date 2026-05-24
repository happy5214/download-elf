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

import configparser
import http.cookiejar
import itertools
import re
import sys
import time
from typing import Optional

import requests


def main() -> int:
    try:
        sequence_base = sys.argv[1]
    except IndexError:
        print('You must pass a sequence as a parameter')
        return 1
    elf_contents = download_elf(sequence_base)
    write_elf(elf_contents, f'alq_{sequence_base}.elf')
    return 0


def download_elf(sequence_base: str) -> list[tuple[int, str]]:
    elf_contents = []
    incomplete = True
    first_run = True
    already_exceeded = False
    cookies = get_cookies()
    while incomplete:
        params = {'seq': sequence_base}
        base = sequence_base
        temp_elf_contents = []
        try:
            with requests.get('https://factordb.com/elf.php', params=params, stream=True, cookies=cookies) as r:
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
                    parsed_line = parse_elf_line(line)
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
                elf_contents.extend(temp_elf_contents)
            else:
                elf_contents.extend(tuple(itertools.takewhile(lambda x: x[0] < 1e199, temp_elf_contents)))
                already_exceeded = True
            base = elf_contents[-1][0]
        if bad_file:
            print('Download error, sleeping 5 seconds...')
            time.sleep(5)
        else:
            first_run = False
            sequence_base = str(base)
            size = len(elf_contents) - 1
            print(f'Now at {size} lines.')
    return elf_contents


def get_cookies() -> http.cookiejar.CookieJar:
    login_info = get_login()
    if login_info:
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
    else:
        print('Running anonymously.')
    return r.cookies


def get_login() -> Optional[dict]:
    config = configparser.ConfigParser()
    config.read('factordb_user.ini')
    if config.has_section('Account'):
        return config['Account']
    else:
        return None


def parse_elf_line(elf_line: str) -> tuple[int, Optional[str]]:
    elf_line_format = r'^\d+ \.\s+(\d+) = (\d+(?:\^\d+)?(?: \* \d+(?:\^\d+)?)*)?$'
    match = re.match(elf_line_format, elf_line)
    if match:
        return (int(match[1]), match[2])
    else:
        return (0, 0)


def write_elf(elf_contents: list[tuple[int, str]], filename: str) -> None:
    with open(filename, 'wt') as elf_file:
        for i, line in enumerate(elf_contents):
            print(f'{i} .   {line[0]} = {line[1]}', file=elf_file)


if __name__ == "__main__":
    sys.exit(main())
