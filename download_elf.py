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

import re
import sys
import time
from typing import Optional

import requests


elf_line_format = re.compile(r'^\d+ \.\s+(\d+) = (\d+(?:\^\d+)?(?: \* \d+(?:\^\d+)?)*)?$')


def parse_elf_line(elf_line: str) -> tuple[int, Optional[str]]:
    match = elf_line_format.match(elf_line)
    if match:
        return (int(match[1]), match[2])
    else:
        return (0, 0)


def download_elf(sequence_base: str) -> list[tuple[int, str]]:
    elf_contents = []
    incomplete = True
    first_run = True
    while incomplete:
        params = {'seq': sequence_base}
        base = sequence_base
        try:
            with requests.get('https://factordb.com/elf.php', params=params, stream=True) as r:
                bad_file = False
                for line in r.iter_lines(decode_unicode=True):
                    parsed_line = parse_elf_line(line)
                    if parsed_line[1] == 0:
                        bad_file = True
                        break
                    if not first_run:
                        first_run = True
                        continue
                    if parsed_line[1] is None:
                        if not incomplete:
                            elf_contents.append((parsed_line[0], ''))
                        break
                    if parsed_line[0] < 1e199:
                        base = parsed_line[0]
                    elf_contents.append(parsed_line)
                if not bad_file:
                    incomplete = False
        except requests.exceptions.ChunkedEncodingError:
            pass
        if bad_file:
            print('Download error, sleeping 5 seconds...')
            time.sleep(5)
        else:
            first_run = False
            sequence_base = str(base)
            size = len(elf_contents) - 1
            print(f'Now at {size} lines.')
    return elf_contents


def write_elf(elf_contents: list[tuple[int, str]], filename: str) -> None:
    with open(filename, 'wt') as elf_file:
        for i, line in enumerate(elf_contents):
            print(f'{i} .   {line[0]} = {line[1]}', file=elf_file)


def main() -> int:
    try:
        sequence_base = sys.argv[1]
    except IndexError:
        print('You must pass a sequence as a parameter')
        return 1
    elf_contents = download_elf(sequence_base)
    write_elf(elf_contents, f'{sequence_base}.elf')
    return 0


if __name__ == "__main__":
    sys.exit(main())
