#!/usr/bin/python3
# -*- coding: utf-8 -*-

"""

svn2git.py

Adapted from <https://github.com/nirvdrum/svn2git>
(Ruby tool for importing existing svn projects into git)

Upstream ruby tool: (c) 2008 James Coglan, Kevin Menard

This python port: (c) 2021 Rainer Schwarzbach

License: MIT, see LICENSE file

"""


import argparse
import datetime
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

# Commit data keys and pretty-printing formats
CD_COMMENT = 'commit comment'
CD_DATE = 'commit date'
CD_AUTHOR_NAME = 'commit author name'
CD_AUTHOR_EMAIL = 'commit author email'

COMMIT_DATA_FORMATS = {
    CD_COMMENT: '%s',
    CD_DATE: '%ci',
    CD_AUTHOR_NAME: '%an',
    CD_AUTHOR_EMAIL: '%ae'}

# 'git config' scopes
CONFIG_GLOBAL = '--global'
CONFIG_LOCAL = '--local'

# Environment variable names
ENV_GIT_COMMITTER_DATE = 'GIT_COMMITTER_DATE'

SCRIPT_NAME = os.path.basename(__file__)

# Read the (script) version from version.txt
with open(os.path.join(os.path.dirname(sys.argv[0]), 'version.txt'),
          mode='rt') as version_file:
    VERSION = version_file.read().strip()
#


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
    abort_time = datetime.datetime.now()
    logging.info(
        '%s %s aborted at %s',
        SCRIPT_NAME,
        VERSION,
        abort_time)
    sys.exit(RETURNCODE_ERROR)


def get_command_output(*command, exit_on_error=True, **kwargs):
    """Run the specified command and return its output
    (stdout and stderr combined).
    if "exit_on_error" is set True (the default),
    this script will exit with an error mesage
    if the command returncode is non-zero.
    """
    kwargs.update(
        dict(check=exit_on_error,
             stdout=subprocess.PIPE,
             stderr=subprocess.PIPE,
             loglevel=logging.DEBUG))
    if kwargs.get('env', '') is not None:
        kwargs['env'] = ENV
    #
    try:
        command_result = processwrappers.get_command_result(
            command, **kwargs)
    except subprocess.CalledProcessError as error:
        exit_with_error(
            '[Command failed] %s\n'
            'Returncode: %s\n'
            '___ Standard error ___\n%s',
            '___ Standard output ___\n%s',
            processwrappers.future_shlex_join(error.cmd),
            error.returncode,
            error.stderr.decode(),
            error.stdout.decode())
    #
    output_lines = []
    for stderr_line in command_result.stderr.decode().splitlines():
        logging.debug('[Command stderr] %s', stderr_line)
        output_lines.append(stderr_line)
    #
    for stdout_line in command_result.stdout.decode().splitlines():
        logging.debug('[Command stdout] %s', stdout_line)
        output_lines.append(stdout_line)
    #
    return '\n'.join(output_lines)


def run_long_task(*command, **kwargs):
    """Run the specified long running task and return its returncode.
    The output streams (stdout and stderr) are not captured,
    allowing normal user interaction with the command
    (eg. for password input).
    If the  command returncode is non-zero,
    this script will exit with an error message.
    """
    kwargs.update(
        dict(check=True,
             stderr=None,
             stdout=None,
             loglevel=logging.INFO))
    if kwargs.get('env', '') is not None:
        kwargs['env'] = ENV
    #
    try:
        command_result = processwrappers.get_command_result(
            command, **kwargs)
    except subprocess.CalledProcessError as error:
        exit_with_error(
            '[Long running task failed] %s\n'
            'Returncode: %s\n',
            processwrappers.future_shlex_join(error.cmd),
            error.returncode)
    #
    return command_result.returncode


def find_branches(remote=False):
    """Yield local or remote branches,
    taking care to ignore console color codes and ignoring the
    '*' character used to indicate the currently selected branch.
    """
    command = [GIT, 'branch']
    if remote:
        command.append('-r')
    #
    for branch in get_command_output(*command, '--no-color').splitlines():
        branch = branch.replace('*', '').strip()
        if branch:
            yield branch
        #
    #


def optimize_repos():
    """Optimize the git repository"""
    logging.info('--- Optimize Repository ---')
    run_long_task(GIT, 'gc')


def verify_working_tree_is_clean():
    """Check if there are no pending local changes.
    Exit if there are any.
    """
    logging.info('--- Verify working tree is clean ---')
    tree_status_output = get_command_output(
        GIT, 'status', '--porcelain', '--untracked-files=no')
    if tree_status_output.strip():
        exit_with_error(
            'You have local pending changes:\n%s\n'
            'The working tree must be clean in order to continue.',
            tree_status_output)
    #


#
# Classes
#


class GitConfigurator:

    """Wrapper for a subset of possible git config calls:
    git config [ --global | --local ] <key> <value>
    git --get [ --global | --local ] <key>
    git --unset [ --global | --local ] <key>

    The --global or --local option is passed via scope
    and always defaults to --local.
    """

    long_option_prefix = '--'

    def __init__(self, local_config_enabled=True):
        """Set the internal __local_config_enabled attribute"""
        self.__local_config_enabled = local_config_enabled

    def __check_key(self, key):
        """Prevent programming errors:
        raise a ValueError if key starts with '--'
        """
        if key.startswith(self.long_option_prefix):
            raise ValueError('Invalid key for git config: %r!' % key)
        #

    def __execute(self, *args, scope=CONFIG_LOCAL, **kwargs):
        """Execute the 'git config' command"""
        command = [GIT, 'config']
        if scope == CONFIG_GLOBAL or (
                scope == CONFIG_LOCAL and self.__local_config_enabled):
            command.append(scope)
        #
        return get_command_output(*command, *args, **kwargs)

    def __call__(self, key, value, scope=CONFIG_LOCAL, **kwargs):
        """git config <scope> <key> <value>"""
        self.__check_key(key)
        return self.__execute(key, value, scope=scope, **kwargs)

    def get(self, key, scope=CONFIG_LOCAL, **kwargs):
        """git config <scope> --get <key>"""
        self.__check_key(key)
        return self.__execute('--get', key, scope=scope, **kwargs)

    def unset(self, key, scope=CONFIG_LOCAL, **kwargs):
        """git config <scope> --unset <key>"""
        self.__check_key(key)
        return self.__execute('--unset', key, scope=scope, **kwargs)


class Migration:

    """Subversion -> Git migration god object"""

    def __init__(self, arguments):
        """Define instance variables"""
        self.options = arguments
        self.__initial_branch = 'master'
        self.local_branches = set()
        self.remote_branches = set()
        self.tags = set()
        self.git_config = GitConfigurator()

    def run(self):
        """Execute the migration depending on the arguments"""
        start_time = datetime.datetime.now()
        logging.info(
            '%s %s started at %s',
            SCRIPT_NAME,
            VERSION,
            start_time)
        if self.options.svn_url:
            self._clone()
            self._get_branches()
        else:
            # --rebase or --rebasebranch specified
            verify_working_tree_is_clean()
            if self.options.rebase:
                self._get_branches()
            elif self.options.rebasebranch:
                self._get_branches()
                self._get_rebasebranch()
            #
        #
        self._fix_branches()
        self._fix_tags()
        self._fix_trunk()
        optimize_repos()
        finish_time = datetime.datetime.now()
        logging.info(
            '%s %s finished at %s',
            SCRIPT_NAME,
            VERSION,
            finish_time)
        duration = (finish_time - start_time).total_seconds()
        logging.info('Elapsed time: %d seconds', duration)
        return RETURNCODE_OK

    def __do_git_svn_init(self):
        """Execute the 'git svn init' command"""
        logging.info('--- Do Git SVN Init ---')
        command = [GIT, 'svn', 'init', '--prefix=svn/']
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
            return run_long_task(*command)
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
        return run_long_task(*command)

    def __do_git_svn_fetch(self):
        """Execute the 'git svn fetch' command"""
        logging.info('--- Do Git SVN Fetch ---')
        command = [GIT, 'svn', 'fetch']
        if self.options.revision:
            revisions_range = self.options.revision.split(':')
            from_revision = revisions_range[0]
            try:
                to_revision = revisions_range[1]
            except IndexError:
                to_revision = 'HEAD'
            #
            command.append('-r')
            command.append(f'{from_revision}:{to_revision}')
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
        return run_long_task(*command)

    def _clone(self):
        """Clone the Subversion repository"""
        logging.info('=== Clone ===')
        self.__do_git_svn_init()
        # Check if local config is possible
        logging.debug(
            'Testing if the --local option is supported by git config …')
        config_output = self.git_config.get(CI_USER_NAME, exit_on_error=False)
        if 'unknown option' in config_output.lower():
            self.git_config = GitConfigurator(local_config_enabled=False)
            logging.debug(
                '[no] --local option is not supported,'
                ' omitting it in future config commands.')
        else:
            logging.debug(
                '[yes] --local option is supported.')
        #
        if os.path.isfile(self.options.authors_file):
            logging.info('Using authors file: %s', self.options.authors_file)
            self.git_config('svn.authorsfile', self.options.authors_file)
        #
        self.__do_git_svn_fetch()

    def _fix_branches(self):
        """Fix branches"""
        logging.info('--- Fix Branches ---')
        svn_branches = {
            branch for branch in self.remote_branches - self.tags
            if PRX_SVN_PREFIX.match(branch)}
        logging.debug('Found branches: %r', svn_branches)
        if self.options.rebase:
            logging.info('Doing the SVN fetch; this will take some time …')
            run_long_task(GIT, 'svn', 'fetch')
        #
        cannot_setup_tracking_information = False
        legacy_svn_branch_tracking_message_displayed = False
        for branch in sorted(svn_branches):
            branch = PRX_SVN_PREFIX.sub('', branch)
            remote_svn_branch = f'remotes/svn/{branch}'
            if self.options.rebase and (branch in self.local_branches
                                        or branch == DEFAULT_TRUNK):
                if branch == DEFAULT_TRUNK:
                    local_branch = self.__initial_branch
                else:
                    local_branch = branch
                #
                get_command_output(GIT, 'checkout', '-f', local_branch)
                get_command_output(GIT, 'rebase', remote_svn_branch)
                continue
            #
            if (branch in self.local_branches
                    or branch == DEFAULT_TRUNK):
                continue
            #
            untracked_checkout = (
                GIT, 'checkout', '-b', branch, remote_svn_branch)
            if cannot_setup_tracking_information:
                get_command_output(*untracked_checkout)
            else:
                track_output = get_command_output(
                    GIT, 'branch', '--track', branch, remote_svn_branch,
                    exit_on_error=False)
                # As of git 1.8.3.2, tracking information cannot be
                # set up for remote SVN branches:
                # <http://git.661346.n2.nabble.com/
                #  git-svn-Use-prefix-by-default-td7594288.html#a7597159>
                #
                # Older versions of git can do it and it should
                # be safe as long as remotes aren't pushed.
                # Our --rebase option obviates the need
                # for read-only tracked remotes, however.
                # So, we'll deprecate the old option,
                # informing those relying on the old behavior
                # that they should use the newer --rebase option.
                if 'cannot setup tracking information' in track_output.lower():
                    cannot_setup_tracking_information = True
                    logging.debug('The above "fatal" message can be ignored.')
                    logging.debug(
                        'It just means your Git version is 1.8.3.2 or newer.')
                    get_command_output(*untracked_checkout)
                else:
                    if not legacy_svn_branch_tracking_message_displayed:
                        logging.warning('*' * 68)
                        for line in (
                                'svn2git warning:,'
                                'Tracking remote SVN branches is deprecated.',
                                'In a future release local branches'
                                ' will be created without tracking.',
                                'If you have to resync your branches, run:',
                                '  svn2git.py --rebase'):
                            logging.warning(line)
                        logging.warning('*' * 68)
                        legacy_svn_branch_tracking_message_displayed = True
                    #
                    get_command_output(GIT, 'checkout', branch)
                #
            #
        #

    def _fix_tags(self):
        """Convert the svn/tags/* branches to git tags"""
        logging.info('--- Fix Tags ---')
        saved_originals = {
            key: self.git_config.get(key, exit_on_error=False).strip()
            for key in (CI_USER_NAME, CI_USER_EMAIL)}
        try:
            for tag_name in sorted(self.tags):
                # Get commit data from the (latest) commit of a
                # svn/tags/… branch (following the convention for svn,
                # there should only be one),
                # produce a git tag using these data
                # and delete the now-obsolete branch.
                tag_name = tag_name.strip()
                tag_id = PRX_SVNTAGS_PREFIX.sub('', tag_name)
                commit_data = {
                    key: get_command_output(
                        GIT, 'log', '-1',
                        f'--pretty=format:{value}', tag_name)
                    for (key, value) in COMMIT_DATA_FORMATS.items()}
                self.git_config(CI_USER_NAME, commit_data[CD_AUTHOR_NAME])
                self.git_config(CI_USER_EMAIL, commit_data[CD_AUTHOR_EMAIL])
                original_git_committer_date = ENV.get(ENV_GIT_COMMITTER_DATE)
                ENV[ENV_GIT_COMMITTER_DATE] = commit_data[CD_DATE]
                get_command_output(
                    GIT, 'tag', '-a',
                    '-m', commit_data[CD_COMMENT],
                    tag_id, tag_name)
                if original_git_committer_date is None:
                    del ENV[ENV_GIT_COMMITTER_DATE]
                else:
                    ENV[ENV_GIT_COMMITTER_DATE] = original_git_committer_date
                #
                get_command_output(GIT, 'branch', '-d', '-r', tag_name)
            #
        finally:
            # We only change the git config values
            # if there are self.tags available.
            # So it stands to reason we should revert them only in that case.
            if self.tags:
                for (key, value) in saved_originals.items():
                    if value:
                        self.git_config(key, value)
                    else:
                        self.git_config.unset(key)
                    #
                #
            #
        #

    def _fix_trunk(self):
        """Fix trunk."""
        logging.info('--- Fix Trunk ---')
        if self.options.rebase and DEFAULT_TRUNK in self.remote_branches:
            for command in (
                    (GIT, 'checkout', 'svn/trunk'),
                    (GIT, 'branch', '-D', self.__initial_branch),
                    (GIT, 'checkout', '-f', '-b', self.__initial_branch)):
                get_command_output(*command)
            #
        else:
            get_command_output(GIT, 'checkout', '-f', self.__initial_branch)
        #

    def _get_branches(self):
        """Get local and remote branches, and tags.
        Store each of them in the appropriate set.
        """
        logging.info('--- Get Branches ---')
        self.local_branches = set(find_branches())
        self.remote_branches = set(find_branches(remote=True))
        # Tags are remote branches that start with "tags/".
        self.tags = {
            single_branch for single_branch in self.remote_branches
            if PRX_SVNTAGS_PREFIX.match(single_branch)}

    def _get_rebasebranch(self):
        """Rebase the specified branch"""
        logging.info('--- Get Rebasebranch ---')
        local_branch_candidates = {
            branch for branch in self.local_branches
            if branch == self.options.rebasebranch}
        remote_branch_candidates = {
            branch for branch in self.remote_branches
            if self.options.rebasebranch in branch}
        try:
            found_local_branch = local_branch_candidates.pop()
        except KeyError:
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
        self.local_branches = {found_local_branch}
        self.remote_branches = remote_branch_candidates
        logging.info('Found local branch %r.', found_local_branch)
        logging.info(
            'Found remote branches %s.'
            ' and '.join(repr(branch) for branch in self.remote_branches))
        # We only rebase the specified branch
        self.tags = set()


#
# Functions
#


def __get_arguments():
    """Parse command line arguments"""
    argument_parser = argparse.ArgumentParser(
        description='Migrate projects from Subversion to Git')
    argument_parser.set_defaults(loglevel=logging.INFO)
    action_mutex = argument_parser.add_mutually_exclusive_group(required=True)
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
        '--authors',
        dest='authors_file',
        metavar='AUTHORS_FILE',
        default=DEFAULT_AUTHORS_FILE,
        help='Path to file containing svn-to-git authors mapping'
        ' (default: %(default)s)')
    argument_parser.add_argument(
        '--exclude',
        metavar='REGEX',
        nargs='+',
        help='Specify a Perl regular expression to filter paths'
        ' to exclude from fetching; can be used multiple times')
    argument_parser.add_argument(
        '-m', '--metadata',
        action='store_true',
        help='Include metadata in git logs (git-svn-id)')
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
    branches_mutex = argument_parser.add_mutually_exclusive_group()
    branches_mutex.add_argument(
        '--branches',
        dest='branches_prefixes',
        metavar='BRANCHES_PATH',
        nargs='+',
        help='Subpath to branches from repository URL (default: %s);'
        ' can be used multiple times' % DEFAULT_BRANCHES)
    branches_mutex.add_argument(
        '--nobranches',
        action='store_true',
        help='Do not try to import any branches')
    tags_mutex = argument_parser.add_mutually_exclusive_group()
    tags_mutex.add_argument(
        '--tags',
        dest='tags_prefixes',
        metavar='TAGS_PATH',
        nargs='+',
        help='Subpath to tags from repository URL (default: %s);'
        ' can be used multiple times' % DEFAULT_TAGS)
    tags_mutex.add_argument(
        '--notags',
        action='store_true',
        help='Do not try to import any tags')
    trunk_mutex = argument_parser.add_mutually_exclusive_group()
    trunk_mutex.add_argument(
        '--trunk',
        dest='trunk_prefix',
        metavar='TRUNK_PATH',
        default=DEFAULT_TRUNK,
        help='Subpath to trunk from repository URL (default: %(default)s)')
    trunk_mutex.add_argument(
        '--notrunk',
        action='store_true',
        help='Do not import anything from trunk')
    argument_parser.add_argument(
        '--rootistrunk',
        action='store_true',
        help='Use this if the root level of the repo is equivalent'
        ' to the trunk and there are no tags or branches.'
        ' In that case, any other options regarding trunk, tags or branches'
        ' will be ignored.')
    action_mutex.add_argument(
        '--rebase',
        action='store_true',
        help='Instead of cloning a new project,'
        ' rebase an existing one against SVN')
    action_mutex.add_argument(
        '--rebasebranch',
        help='Rebase the specified branch')
    action_mutex.add_argument(
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
