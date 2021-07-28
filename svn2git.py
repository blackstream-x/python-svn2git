#!/usr/bin/python3
# -*- coding: utf-8 -*-

"""

svn2git.py

Adapted from <https://github.com/nirvdrum/svn2git>
(Ruby tool for importing existing svn projects into git)

Python port (c) 2021 by Rainer Schwarzbach

License: MIT, see LICENSE file

"""


import argparse
import locale
import logging
import os
import re
import subprocess
import sys

# local module

import processwrappers


#
# Constants
#


DEFAULT_AUTHORS_FILE = '~/.svn2git/authors'
DEFAULT_BRANCHES = 'branches'
DEFAULT_TAGS = 'tags'
DEFAULT_TRUNK = 'trunk'

MESSAGE_FORMAT_PURE = '%(message)s'
MESSAGE_FORMAT_WITH_LEVELNAME = '%(levelname)-8s\u2551 %(message)s'

PRX_SVNTAGS_PREFIX = re.compile(r'svn/tags/')

RETURNCODE_OK = 0
RETURNCODE_ERROR = 1

locale.setlocale(locale.LC_ALL, '')
ENCODING = locale.getpreferredencoding()


#
# Helper Functions
#


def exit_with_error(msg, *args):
    """Exit after logging the given error message
    (which may stretch over multiple lines).
    """
    if args:
        msg = msg % args
    #
    for line in msg.splitlines():
        logging.error(line)
    #
    sys.exit(RETURNCODE_ERROR)


#
# Classes
#


class Migration:

    """Subversion -> Git migration"""

    def __init__(self, arguments):
        """Define instance variables"""
        self.options = arguments
        self.__git_config_command = 'git config --local'.split()
        config_status = self.__do_git_config(
            '--get', 'user.name', exit_on_error=False)
        if 'unknown option' in config_status.lower():
            self.__git_config_command = 'git config'.split()
        #
        self.local_branches = []
        self.remote_branches = []
        self.tags = []

    def run(self):
        """Execute the migration depending on the arguments"""
        if self.options.svn_url:
            self._clone()
        else:
            # --rebase or --rebasebranch specified
            self._verify_working_tree_is_clean()
            if self.options.rebase:
                self._get_branches()
            if self.options.rebasebranch:
                self._get_rebasebranch()
            #
        #
        self._fix_branches()
        self._fix_tags()
        self._fix_trunk()
        self._optimize_repos()
        return RETURNCODE_OK

    @staticmethod
    def run_command(command,
                    exit_on_error=True,
                    print_output=False,
                    **kwargs):
        """Run the specified command and return its output
        In the first iteration: simple stdout and stderr capturing,
        later versions might add streaming output
        """
        kwargs.update(
            dict(check=exit_on_error,
                 stdout=subprocess.PIPE,
                 stderr=subprocess.STDOUT,
                 loglevel=logging.DEBUG))
        command_result = processwrappers.get_command_result(
            command, **kwargs)
        output = command_result.stdout.decode(ENCODING)
        if print_output:
            print(output)
        else:
            for line in output.splitlines():
                logging.debug(line)
            #
        #
        return output

    def __do_git_config(self, *args, exit_on_error=True, print_output=False):
        """Execute the stored git config command with
        the provided arguments
        """
        return self.run_command(
            self.__git_config_command + args,
            exit_on_error=exit_on_error,
            print_output=print_output)

    def __do_git_svn_init(self):
        """Execute the 'git svn init' command"""
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
            command.append(f'--trunk={self.options.svn_url}')
            return self.run_command(
                command, exit_on_error=True, print_output=True)
        #
        if self.options.trunk_prefix:
            command.append(f'--trunk={self.options.trunk_prefix}')
        #
        for tags_prefix in self.options.tags_prefixes:
            command.append(f'--tags={tags_prefix}')
        #
        for branches_prefix in self.options.branches_prefixes:
            command.append(f'--branches={branches_prefix}')
        #
        command.append(self.options.svn_url)
        return self.run_command(
            command, exit_on_error=True, print_output=True)

    def __do_git_svn_fetch(self):
        """Execute the 'git svn fetch' command"""
        command = 'git svn fetch'.split()
        if self.options.revision:
            revisions_range = self.options.revision.split(':')
            from_revision = revisions_range[0]
            try:
                to_revision = revisions_range[1]
            except IndexError:
                to_revision = 'HEAD'
            #
            command.extend(('-r', f'{from_revision}:{to_revision}'))
        #
        if self.options.exclude:
            exclude_prefixes = []
            if self.options.trunk_prefix:
                exclude_prefixes.append(f'{self.options.trunk_prefix}[/]')
            #
            for tags_prefix in self.options.tags_prefixes:
                exclude_prefixes.append(f'{tags_prefix}[/][^/]+[/]')
            #
            for branches_prefix in self.options.branches_prefixes:
                exclude_prefixes.append(f'{branches_prefix}[/][^/]+[/]')
            #
            regex = '^(?:%s)(?:%s)' % (
                '|'.join(exclude_prefixes),
                '|'.join(self.options.exclude))
            command.append(f'--ignore-paths={regex}')
        #
        return self.run_command(
            command, exit_on_error=True, print_output=True)

    def _get_branches(self):
        """Get the list of local and remote branches,
        taking care to ignore console color codes and ignoring the
        '*' character used to indicate the currently selected branch.
        """
        found_branches = {}
        for branch_type in ('-l', '-r'):
            found_branches[branch_type] = []
            for branch in self.run_command((
                    'git', 'branch', branch_type, '--no-color')).splitlines():
                branch = branch.replace('*', '').strip()
                if branch:
                    found_branches[branch_type].append(branch)
                #
            #
        #
        self.local_branches = found_branches['-l']
        self.remote_branches = found_branches['-r']
        # Tags are remote branches that start with "tags/".
        self.tags = [
            single_branch for single_branch in self.remote_branches
            if PRX_SVNTAGS_PREFIX.match(single_branch)]

    def _get_rebasebranch(self):
        """Rebase the specified branch"""
        self._get_branches()    # "Explicit is better than implicit"
        local_branch_candidates = [
            branch for branch in self.local_branches
            if branch == self.options.rebasebranch]
        remote_branch_candidates = [
            branch for branch in self.remote_branches
            if self.options.rebasebranch in branch]
        try:
            found_local_branch = local_branch_candidates.pop()
        except IndexError:
            exit_with_error(
                'No local branches named %r found.',
                self.options.rebasebranch)
        #
        if local_branch_candidates:
            exit_with_error(
                'Too many matching local branches found: %s, %s.',
                found_local_branch,
                ', '.join(local_branch_candidates))
        #
        if not remote_branch_candidates:
            exit_with_error(
                'No remote branches named %r found.',
                self.options.rebasebranch)
        #
        if len(remote_branch_candidates) > 2:
            # 1 if remote is not pushed, 2 if its pushed to remote
            exit_with_error(
                'Too many matching remote branches found: %s.',
                ', '.join(remote_branch_candidates))
        #
        self.local_branches = [found_local_branch]
        self.remote_branches = remote_branch_candidates
        logging.info('Found local branch %r.', found_local_branch)
        logging.info(
            'Found remote branches %s.'
            ' and '.join(repr(branch) for branch in self.remote_branches))
        # We only rebase the specified branch
        self.tags = []

    def _clone(self):
        """..."""
        self.__do_git_svn_init()
        if os.path.isfile(self.options.authors):
            self.__do_git_config('svn.authorsfile', self.options.authors)
        #
        self.__do_git_svn_fetch()
        self._get_branches()

    def _fix_branches(self):
        """..."""
        raise NotImplementedError

    def _fix_tags(self):
        """Convert the tags/* branches to git tags"""
        parameters_to_save = ('user.name', 'user.emails')
        saved_originals = {
            key: self.__do_git_config(
                '--get', key, exit_on_error=False).strip()
            for key in parameters_to_save}
        pretty_format = dict(
            subject='%s',
            commit_date='%ci',
            author_name='%an',
            author_email='%ae')
        env = dict(os.environ)
        try:
            for tag_name in self.tags:
                tag_name = tag_name.strip()
                tag_id = PRX_SVNTAGS_PREFIX.sub('', tag_name)
                commit_data = {
                    key: self.run_command((
                        'git', 'log', '-1',
                        f'--pretty=format:{value}', tag_name))
                    for (key, value) in pretty_format.items()}
                self.__do_git_config(
                    'user.name', commit_data['author_name'])
                self.__do_git_config(
                    'user.email', commit_data['author_email'])
                original_git_committer_date = env.get('GIT_COMMITTER_DATE')
                env['GIT_COMMITTER_DATE'] = commit_data['commit_date']
                self.run_command((
                    'git', 'tag', '-a', '-m', commit_data['subject'],
                    tag_id, tag_name), env=env)
                if original_git_committer_date is None:
                    del env['GIT_COMMITTER_DATE']
                else:
                    env['GIT_COMMITTER_DATE'] = original_git_committer_date
                #
                self.run_command(('git', 'branch', '-d', '-r', tag_name))
            #
        finally:
            # We only change the git config values
            # if there are self.tags available.
            # So it stands to reason we should revert them only in that case.
            if self.tags:
                for (key, value) in saved_originals.items():
                    if value:
                        self.__do_git_config(key, value)
                    else:
                        self.__do_git_config('--unset', key)
                    #
                #
            #
        #

    def _fix_trunk(self):
        """..."""
        raise NotImplementedError

    def _optimize_repos(self):
        """Optimize the git repository"""
        self.run_command("git gc")

    def _verify_working_tree_is_clean(self):
        """Check if there are no pending local changes"""
        tree_status = self.run_command(
            'git status --porcelain --untracked-files=no'.split())
        if tree_status.strip():
            exit_with_error(
                'You have local pending changes.\n'
                ' The working tree must be clean in order to continue.')
        #


#
# Functions
#


def __get_arguments():
    """Parse command line arguments"""
    argument_parser = argparse.ArgumentParser(
        description='Description')
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
        dest='trunk_prefix',
        metavar='TRUNK_PATH',
        default=DEFAULT_TRUNK,
        help='Subpath to trunk from repository URL (default: %(default)s)')
    argument_parser.add_argument(
        '--branches',
        dest='branches_prefixes',
        metavar='BRANCHES_PATH',
        nargs='+',
        help='Subpath to branches from repository URL (default: %s);'
        ' can be used multiple times' % DEFAULT_BRANCHES)
    argument_parser.add_argument(
        '--tags',
        dest='tags_prefixes',
        metavar='TAGS_PATH',
        nargs='+',
        default='tags',
        help='Subpath to tags from repository URL (default: %s);'
        ' can be used multiple times' % DEFAULT_TAGS)
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
        'svn_url',
        metavar='SVN_URL',
        nargs='?',
        help='Subversion repository URL')
    arguments = argument_parser.parse_args()
    logging.basicConfig(format=MESSAGE_FORMAT_WITH_LEVELNAME,
                        level=arguments.loglevel)
    # Set branches, tags and trunk prefixes
    if arguments.rootistrunk or arguments.nobranches:
        arguments.branches_prefixes = []
    elif not arguments.branches_prefixes:
        arguments.branches_prefixes = [DEFAULT_BRANCHES]
    #
    if arguments.rootistrunk or arguments.notags:
        arguments.tags_prefixes = []
    elif not arguments.tags_prefixes:
        arguments.tags_prefixes = [DEFAULT_TAGS]
    #
    if arguments.rootistrunk or arguments.notrunk:
        arguments.trunk_prefix = None
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
