#!/usr/bin/python3
# -*- coding: utf-8 -*-

"""

push_all.py

Adapted from <https://github.com/nirvdrum/svn2git>
(Ruby tool for importing existing svn projects into git)

Copyright (c) 2021      Rainer Schwarzbach

License: MIT, see LICENSE file

"""


import argparse
import datetime
import logging
import os
import re
import sys

# local module

import gitwrapper


#
# Constants
#


MESSAGE_FORMAT_PURE = '%(message)s'
MESSAGE_FORMAT_WITH_LEVELNAME = '%(levelname)-8s\u2551 %(message)s'

PRX_SVNTAGS_PREFIX = re.compile(r'^svn/tags/')
PRX_SVN_PREFIX = re.compile(r'^svn/')

RETURNCODE_OK = 0
RETURNCODE_ERROR = 1

ENV = dict(os.environ)
ENV['LANG'] = 'C'       # Prevent command output translation

# Git executable
GIT = 'git'

# Config items
CI_USER_NAME = 'user.name'
CI_USER_EMAIL = 'user.email'

SCRIPT_NAME = os.path.basename(__file__)

# Read the (script) version from version.txt
with open(os.path.join(os.path.dirname(sys.argv[0]), 'version.txt'),
          mode='rt') as version_file:
    VERSION = version_file.read().strip()
#


#
# Classes
#


class Push:

    """Push the contents of the local Git repository to origin.

    When pushing branches in batch mode,
    reduce (half) the batch size in the current branch
    if there is a failure and try again
    until either the failures are resolved, or batch size is 1 and the
    failure remains
    """

    def __init__(self, arguments):
        """Store the given options internally"""
        self.options = arguments
        self.git = gitwrapper.GitWrapper(env=ENV, git_command=GIT)

    def run(self):
        """Start the push"""
        # 1. Check for the --origin option
        # 2. check for git config credential.helper or
        #    the --ignore-missing-credential-helper option
        # 3. if not options.batch_size:
        #        git push -u origin --all
        #    else:
        #        Loop over branches and push in batches
        # 4. If not options.batch_size and no unresolved branch failures:
        #        git push -u origin --tags
        #    else:
        #        push tags one after another
        #
        raise NotImplementedError


#
# Functions
#


def __get_arguments():
    """Parse command line arguments"""
    argument_parser = argparse.ArgumentParser(
        description='Migrate projects from Subversion to Git')
    argument_parser.set_defaults(loglevel=logging.INFO)
    argument_parser.add_argument(
        '-v', '--verbose',
        action='store_const',
        const=logging.DEBUG,
        dest='loglevel',
        help='Output all messages including debug level')
    argument_parser.add_argument(
        '--origin',
        metavar='NAME',
        help='Origin to push to (if not given,'
        'an existing origin will be used')
    argument_parser.add_argument(
        '--batch-size',
        type=int,
        default=0,
        help='Initial batch size (the number of commits that will be'
        ' pushed; set to 1000, it will be reduced automatically...).'
        ' If this option is not given or set to zero,'
        ' a global push will be attempted.')
    argument_parser.add_argument(
        '--ignore-failures',
        action='store_true',
        help='Continue even if failures could not be resolved.')
    arguments = argument_parser.parse_args()
    if arguments.batch_size < 0:
        gitwrapper.exit_with_error(
            'Invalid batch size %s!', arguments.batch_size)
    #
    logging.basicConfig(format=MESSAGE_FORMAT_WITH_LEVELNAME,
                        level=arguments.loglevel)
    #
    return arguments


def main(arguments):
    """Main routine, calling functions from above as required.
    Returns a returncode which is used as the script's exit code.
    """
    push = Push(arguments)
    return push.run()


if __name__ == '__main__':
    # Call main() with the provided command line arguments
    # and exit with its returncode
    sys.exit(main(__get_arguments()))


# vim: fileencoding=utf-8 sw=4 ts=4 sts=4 expandtab autoindent syntax=python:
