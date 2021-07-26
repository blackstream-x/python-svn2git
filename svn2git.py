#!/usr/bin/python3
# -*- coding: utf-8 -*-

"""

Script file name

Description, Copyright, License etc.

"""


import argparse
import logging
import os.path
import re
import shlex
import subprocess
import sys


#
# Constants
#


DEFAULT_AUTHORS_FILE = '~/.svn2git/authors'
DEFAULT_BRANCHES = 'branches'

MESSAGE_FORMAT_PURE = '%(message)s'
MESSAGE_FORMAT_WITH_LEVELNAME = '%(levelname)-8s\u2551 %(message)s'

RETURNCODE_OK = 0
RETURNCODE_ERROR = 1


#
# Classes
#


...


#
# Functions
#


...


def run_command(cmd, exit_on_error=True, printout_output=False):
    """Run the specified command and return its output
    In the first iteration: simple stdout and stderr capturing,
    later versions might add streaming output
    """
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    #
    logging.debug('Running command: %s', cmd)
    try:
        command_result = subprocess.run(
            cmd,
            check=exit_on_error,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError:
        logging.error('Command failed: %s', cmd)
        sys.exit(RETURNCODE_ERROR)
    #
    output = command_result.stdout.decode()
    if printout_output:
        print(output)
    else:
        for line in output.splitlines():
            logging.debug(line)
        #
    #
    return output


def exit_with_error(msg):
    """Exit with an error message"""
    logging.error(msg)
    sys.exit(RETURNCODE_ERROR)


def verify_working_tree_is_clean():
    """Check if there are no pending local changes"""
    tree_status = run_command('git status --porcelain --untracked-files=no')
    if tree_status.strip():
        exit_with_error(
            'You have local pending changes.'
            ' The working tree must be clean in order to continue.')
    #


class Migration:

    """SVN -> git migration"""

    def __init__(self, arguments):
        """Define instance variables"""
        self.options = arguments
        #self.url = self.options.url
        config_status = run_command(
            'git config --local --get user.name',
            exit_on_error=False)
        if 'unknown option' in config_status.lower():
            self.git_config_command = 'git config'
        else:
            self.git_config_command = 'git config --local'
        #
        self.local_branches = []
        self.remote_branches = []
        self.tags = []

    def run(self):
        """Execute the migration depending on the arguments"""
        if self.options.rebase:
            self.get_branches()
        elif self.options.rebasebranch:
            self.get_rebasebranch()
        else:
            self.clone()
        #
        self.fix_branches()
        self.fix_tags()
        self.fix_trunk()
        self.optimize_repos()
        return RETURNCODE_OK

    def get_branches(self):
        """Get the list of local and remote branches,
        taking care to ignore console color codes and ignoring the
        '*' character used to indicate the currently selected branch.
        """
        branches = {}
        for branch_type in 'lr':
            branches[branch_type] = []
            for found_branch in run_command(
                    f'git branch -{branch_type} --no-color').splitlines():
                found_branch = found_branch.replace('*', '').strip()
                if found_branch:
                    branches[branch_type].append(found_branch)
                #
            #
        #
        self.local_branches = branches['l']
        self.remote_branches = branches['r']
        # Tags are remote branches that start with "tags/".
        self.tags = [
            single_branch for single_branch in self.remote_branches
            if single_branch.startswith('tags/')]

    def get_rebasebranch(self):
        """..."""
        raise NotImplementedError

    def clone(self):
        """..."""
        command = 'git svn init --prefix=svn/'.split()
        if self.options.username:
            command.append(f'--username={self.options.username}')
        #
        if self.options.password:
            command.append(f'--password={self.options.password}')
        #
        if not self.options.metadata:
            command.append('--no-metadata')
        #
        if self.options.no_minimize_url:
            command.append('--no-minimize-url')
        #
        if self.options.rootistrunk:
            command.append(f'--trunk={self.options.url}')
            run_command(command, exit_on_error=True, printout_output=True)
        else:
            if not self.options.notrunk:
                command.append(f'--trunk={self.options.trunk}')
            #
            if not self.options.notags:
                for tag in self.options.tags:
                    command.append(f'--tags={tag}')
                #
            #
            if not self.options.nobranches:
                for branch in self.options.branches:
                    command.append(f'--branches={branch}')
                #
            #
            command.append(self.options.url)
            run_command(command, exit_on_error=True, printout_output=True)
        #
        if os.path.isfile(self.options.authors):
            run_command([
                self.git_config_command,
                'svn.authorsfile',
                self.options.authors])
        #
        command = 'git svn fetch'.split()
        if self.options.revision:
            revisions_range = self.options.revision.split(':')
            if len(revisions_range) < 2:
                revisions_range.append('HEAD')
            #
            command.extend(('-r', ':'.join(revisions_range[:2])))
        #
        if self.options.exclude:
            exclude_prefixes = []
            if not self.options.notrunk:
                exclude_prefixes.append(f'{self.options.trunk}[/]')
            #
            if not self.options.notags:
                for tag in self.options.tags:
                    exclude_prefixes.append(f'{tag}[/][^/]+[/]')
                #
            #
            if not self.options.nobranches:
                for branch in self.options.branches:
                    exclude_prefixes.append(f'{branch}[/][^/]+[/]')
                #
            #
            regex = '^(?:%s)(?:%s)' % (
                '|'.join(exclude_prefixes),
                '|'.join(self.options.exclude))
            command.append(f'--ignore-paths={regex}')
        #
        run_command(command, exit_on_error=True, printout_output=True)
        self.get_branches()

    def fix_branches(self):
        """..."""
        raise NotImplementedError

    def fix_tags(self):
        """..."""
        raise NotImplementedError

    def fix_trunk(self):
        """..."""
        raise NotImplementedError

    def optimize_repos(self):
        """Optimize the git repository"""
        run_command("git gc")


def __get_arguments():
    """Parse command line arguments"""
    argument_parser = argparse.ArgumentParser(
        description='Description')
    def exit_with_help_message(msg):
        """Show the message and the script usage, then exit"""
        print(f'Error starting script: {msg}\n')
        argument_parser.print_help()
        sys.exit()
    #
    argument_parser.set_defaults(loglevel=logging.INFO)
    argument_parser.add_argument(
        '-v', '--verbose',
        action='store_const',
        const=logging.DEBUG,
        dest='loglevel',
        help='Output all messages including debug level')
    argument_parser.add_argument(
        '--username',
        metavar='NAME',
        help='Username for transports that need it (http(s), svn)')
    argument_parser.add_argument(
        '--password',
        help='Password for transports that need it (http(s), svn)')
    argument_parser.add_argument(
        '--trunk',
        metavar='TRUNK_PATH',
        default='trunk',
        help='Subpath to trunk from repository URL (default: %(default)s)')
    argument_parser.add_argument(
        '--branches',
        metavar='BRANCHES_PATH',
        nargs='+',
        help='Subpath to branches from repository URL (default: %s);'
        ' can be used multiple times' % DEFAULT_BRANCHES)
    argument_parser.add_argument(
        '--tags',
        metavar='TAGS_PATH',
        nargs='*',
        default='tags',
        help='Subpath to tags from repository URL (default: %(default)s);'
        ' can be used multiple times')
    argument_parser.add_argument(
        '--rootistrunk',
        action='store_true',
        help='Use this if the root level of the repo is equivalent'
        ' to the trunk and there are no tags or branches')
    argument_parser.add_argument(
        '--notrunk',
        action='store_true',
        help='Do not import anything from trunk')
    argument_parser.add_argument(
        '--nobranches',
        action='store_true',
        help='Do not try to import any branches')
    argument_parser.add_argument(
        '--notags',
        action='store_true',
        help='Do not try to import any tags')
    argument_parser.add_argument(
        '--no-minimize-url',
        action='store_true',
        help='Accept URLs as-is without attempting'
        ' to connect to a higher level directory')
    argument_parser.add_argument(
        '--revision',
        metavar='START_REV[:END_REV]',
        help='Start importing from SVN revision START_REV;'
        ' optionally end at END_REV')
    argument_parser.add_argument(
        '-m', '--metadata',
        action='store_true',
        help='Include metadata in git logs (git-svn-id)')
    argument_parser.add_argument(
        '--authors',
        metavar='AUTHORS_FILE',
        default=DEFAULT_AUTHORS_FILE,
        help='Path to file containing svn-to-git authors mapping'
        ' (default: %(default)s)')
    argument_parser.add_argument(
        '--exclude',
        metavar='REGEX',
        nargs='+',
        default='tags',
        help='Specify a Perl regular expression to filter paths'
        ' when fetching; can be used multiple times')
    mutex_group = argument_parser.add_mutually_exclusive_group(required=True)
    mutex_group.add_argument(
        '--rebase',
        action='store_true',
        help='Instead of cloning a new project,'
        ' rebase an existing one against SVN')
    mutex_group.add_argument(
        '--rebasebranch',
        help='Rebase the specified branch')
    mutex_group.add_argument(
        'url',
        metavar='SVN_URL',
        nargs='?',
        help='Subversion repository URL')
    arguments = argument_parser.parse_args()
    logging.basicConfig(format=MESSAGE_FORMAT_WITH_LEVELNAME,
                        level=arguments.loglevel)
    if arguments.rootistrunk:
        arguments.notrunk = True
        arguments.nobranches = True
        arguments.notags = True
    #
    if arguments.nobranches:
        arguments.branches = []
    elif not arguments.branches:
        arguments.branches = [DEFAULT_BRANCHES]
    #
    return arguments


def main(arguments):
    """Main routine, calling functions from above as required.
    Returns a returncode which is used as the script's exit code.
    """
    migration = Migration(arguments)
    return migration.run()


if __name__ == '__main__':
    # Call main() with the provided command line arguments
    # and exit with its returncode
    sys.exit(main(__get_arguments()))


# vim: fileencoding=utf-8 sw=4 ts=4 sts=4 expandtab autoindent syntax=python:
