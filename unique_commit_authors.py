#!/usr/bin/python3
# -*- coding: utf-8 -*-

"""

unique_commit_authors.py

Determine authors from the subversion log,
either that one of the working copy in the current directory
or the log of the repository at the given URL.

Compatibility: Python 3.6+

Copyright (c) 2021      Rainer Schwarzbach

License: MIT, see LICENSE file

"""


import argparse
import datetime
import locale
import logging
import os.path
import re
import sys

# local module

import processwrappers


#
# Constants
#


CHUNK_SIZE = 5000

FS_MESSAGE = '%(levelname)-8s\u2551 %(message)s'

PRX_LOG_ENTRY = re.compile(
    r'^-{60,}\r?\nr(\d+)\s+\|\s*([^\|\n]*?)\s*\|.+?$',
    re.M)

RETURNCODE_OK = 0
RETURNCODE_ERROR = 1

SCRIPT_NAME = os.path.basename(__file__)

locale.setlocale(locale.LC_ALL, '')
ENCODING = locale.getpreferredencoding()


#
# Helper Functions
#


def log_separator(level=logging.INFO):
    """Log a horizontal line as separator"""
    logging.log(level, '-' * 72)


def revision_range(start, end):
    """Return a string representation of a revision range"""
    if start == end:
        return str(end)
    #
    return '%s\u2013%s' % (start, end)


def ranges_list(numbers):
    """Return a list of number representations a strings,
    summarized to ranges where applicable
    """
    if not isinstance(numbers, set):
        raise ValueError('The numbers must be provided as a set!')
    summaries = []
    current_start = None
    last_seen = 0
    for current_number in sorted(numbers):
        if current_start is None:
            current_start = current_number
            last_seen = current_number
            continue
        #
        if current_number > last_seen + 1:
            summaries.append(
                revision_range(current_start, last_seen))
            current_start = current_number
        #
        last_seen = current_number
    #
    summaries.append(revision_range(current_start, last_seen))
    return summaries


#
# Classes
#


class LogExaminer:

    """Log examination class"""

    def __init__(self, options):
        """Store options, examine repository info
        and initialize instance variables
        """
        self.options = options
        self.in_repository_root = True
        url = self.options.svn_url
        if not url:
            local_info = self._get_repository_info()
            url = local_info['Repository Root']
        #
        remote_info = self._get_repository_info(url=url)
        self.repository_root = remote_info['Repository Root']
        self.head_revision = int(remote_info['Revision'])
        self.seen_revisions = set()
        self.revisions_by_author = {}

    def _check_for_missing_revisions(self):
        """Check for missing revisions.
        Return the matching returncode.
        """
        expected_revisions = set(range(1, self.head_revision + 1))
        missing_revisions = expected_revisions - self.seen_revisions
        if missing_revisions:
            logging.error(
                '%s found missing revisions:',
                SCRIPT_NAME)
            logging.error(', '.join(ranges_list(missing_revisions)))
            if self.in_repository_root:
                logging.error(
                    'You probably need to execute an "%s update"!',
                    self.options.svn_command)
            else:
                logging.error(
                    'Try to call this script again from the working copy'
                    ' root directory,')
                logging.error(
                    'or provide the %s URL on the command line.',
                    self.repository_root)
                logging.error(
                    'You also could try an "%s update".',
                    self.options.svn_command)
            log_separator(level=logging.ERROR)
            return RETURNCODE_ERROR
        #
        return RETURNCODE_OK

    def _examine_log_chunks(self):
        """Examine the log using the 'svn log' command, in chunks,
        using the 'finditer' method of a precompiled regular expression,
        and print each author encountered for the first time to stdout
        """
        self.revisions_by_author.clear()
        self.seen_revisions.clear()
        highest_returncode = RETURNCODE_OK
        current_base = 1
        logging.info(
            f'Reading the SVN log in chunks of'
            f' {self.options.chunk_size} revisions')
        while current_base <= self.head_revision:
            current_end = current_base + self.options.chunk_size - 1
            if current_end > self.head_revision:
                current_end = self.head_revision
            #
            command = [self.options.svn_command,
                       'log', '-r', '%s:%s' % (current_base, current_end)]
            if self.options.svn_url:
                command.append(self.repository_root)
            #
            process_result = processwrappers.get_command_result(command)
            if process_result.stderr:
                logging.error(process_result.stderr.decode(ENCODING))
            #
            for revision_match in PRX_LOG_ENTRY.finditer(
                    process_result.stdout.decode(ENCODING)):
                revision = int(revision_match.group(1))
                author = revision_match.group(2)
                if revision in self.seen_revisions:
                    logging.warning('Duplicated revision entry:')
                    logging.warning(revision_match.group(0))
                #
                self.seen_revisions.add(revision)
                try:
                    self.revisions_by_author[author].add(revision)
                except KeyError:
                    print(author)
                    self.revisions_by_author[author] = set([revision])
                #
            #
            highest_returncode = max(
                highest_returncode,
                process_result.returncode)
            logging.info('Examined %r revisions', current_end)
            current_base = current_end + 1
        #
        return highest_returncode

    def _get_repository_info(self, url=None):
        """Return the information read through 'svn info' as a dict"""
        command = [self.options.svn_command, 'info']
        if url:
            command.append(url)
        #
        raw_result = processwrappers.get_command_result(command)
        if raw_result.stderr:
            logging.error(raw_result.stderr.decode(ENCODING))
        #
        details = {}
        repository_root_relative = '^/'
        for line in raw_result.stdout.decode(ENCODING).splitlines():
            if not line.split():
                continue
            #
            keyword, value = line.split(':', 1)
            details[keyword] = value.strip()
        #
        if details['Relative URL'] != repository_root_relative:
            logging.warning(
                'Got unexpected relative URL %r (expected %r)',
                details['Relative URL'],
                repository_root_relative)
            self.in_repository_root = False
        #
        return details

    def _print_generic_statistics(self, duration):
        """Print generic statistics"""
        examined_revisions = len(self.seen_revisions)
        revisions_rate = examined_revisions / duration
        logging.info('%s statistics', SCRIPT_NAME)
        log_separator()
        logging.info(
            'Examined %r revisions in %.3f seconds',
            examined_revisions,
            duration)
        logging.info(
            '(\u00f8 %.1f revisions per second).',
            revisions_rate)
        log_separator()

    def print_per_user_statistics(self):
        """Print per-user statistics"""
        logging.info('%s per-user statistics', SCRIPT_NAME)
        log_separator()
        for (author, revisions) in sorted(
                self.revisions_by_author.items()):
            logging.info(
                '%r commited %d revisions: %s',
                author,
                len(revisions),
                ', '.join(ranges_list(revisions)))
            log_separator()
        #

    def run(self):
        """Output script information, start the log examination
        and print statistics
        """
        start_time = datetime.datetime.now()
        logging.info('%s start at %s', SCRIPT_NAME, start_time)
        logging.info('Repository Root: %s', self.repository_root)
        logging.info('HEAD Revision:   %s', self.head_revision)
        log_separator()
        highest_returncode = self._examine_log_chunks()
        done_time = datetime.datetime.now()
        log_separator()
        logging.info(
            '"%s log" highest returncode: %r',
            self.options.svn_command,
            highest_returncode)
        log_separator()
        self._print_generic_statistics(
            (done_time - start_time).total_seconds())
        if self.options.per_user_statistics:
            self.print_per_user_statistics()
        #
        highest_returncode = max(
            self._check_for_missing_revisions(),
            highest_returncode)
        finish_time = datetime.datetime.now()
        logging.info('%s finish at %s', SCRIPT_NAME, finish_time)
        return highest_returncode


#
# Functions
#


def __get_arguments():
    """Parse command line arguments"""
    argument_parser = argparse.ArgumentParser(
        description='Print unique authors from the subversion log.')
    argument_parser.set_defaults(loglevel=logging.INFO)
    argument_parser.add_argument(
        '-q', '--quiet',
        action='store_const',
        const=logging.WARNING,
        dest='loglevel',
        help='Output error and warning messages only.')
    argument_parser.add_argument(
        '-v', '--verbose',
        action='store_const',
        const=logging.DEBUG,
        dest='loglevel',
        help='Output all messages.')
    argument_parser.add_argument(
        '-c', '--chunk-size',
        type=int,
        default=CHUNK_SIZE,
        help='Split the Subversion log into chunks of CHUNK_SIZE revisions'
        ' (default: %(default)s).')
    argument_parser.add_argument(
        '-s', '--per-user-statistics',
        action='store_true',
        help='Print per-user statistics.')
    argument_parser.add_argument(
        '--svn-command',
        default='svn',
        help='Subversion command line client executable path.'
        ' Normally, the default value (%(default)s) is sufficient,'
        ' but there might exist cases where the executeable is stored'
        ' in a non-standard location not included in the system path'
        ' (e.g. /opt/CollabNet_Subversion/bin/svn).')
    argument_parser.add_argument(
        'svn_url',
        nargs='?',
        help='Subversion repository URL')
    arguments = argument_parser.parse_args()
    logging.basicConfig(format=FS_MESSAGE,
                        level=arguments.loglevel)
    return arguments


def main(arguments):
    """Examine the Subversion log of the working copy in the
    current directory or the log of the repository at the provided URL
    """
    log_examiner = LogExaminer(arguments)
    return log_examiner.run()


if __name__ == '__main__':
    sys.exit(main(__get_arguments()))


# vim: fileencoding=utf-8 sw=4 ts=4 sts=4 expandtab autoindent syntax=python:
