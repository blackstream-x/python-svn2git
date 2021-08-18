#!/usr/bin/python3
# -*- coding: utf-8 -*-

"""

push_all.py

Push the contents of a local Git repository to its
(preconfigurd or set via --set-origin) origin URL.

Copyright (c) 2021      Rainer Schwarzbach

License: MIT, see LICENSE file

"""


import argparse
import datetime
import logging
import os
import sys

# local module

import gitwrapper


#
# Constants
#


MESSAGE_FORMAT_PURE = '%(message)s'
MESSAGE_FORMAT_WITH_LEVELNAME = '%(levelname)-8s\u2551 %(message)s'

RETURNCODE_OK = 0
RETURNCODE_ERROR = 1

ENV = dict(os.environ)
ENV['LANG'] = 'C'       # Prevent command output translation

ORIGIN = 'origin'

# Git executable
GIT = 'git'

# Defaults
DEFAULT_BRANCH_NAMES = {'development', 'main', 'master', 'trunk'}
DEFAULT_MAX_BATCH_SIZE = 1024

SCRIPT_NAME = os.path.basename(__file__)

# Read the (script) version from version.txt
with open(os.path.join(os.path.dirname(sys.argv[0]), 'version.txt'),
          mode='rt') as version_file:
    VERSION = version_file.read().strip()
#


#
# Classes
#


class FullPush:

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
        self.all_branches = []
        self.all_tags = []
        self.branches_failed = {}
        self.branches_pushed = []
        self.tags_failed = []

    def run(self):
        """Do a full push"""
        start_time = datetime.datetime.now()
        logging.info(
            '%s %s started at %s',
            SCRIPT_NAME,
            VERSION,
            start_time)
        logging.info('-' * 72)
        #
        # 1. Check for the origin or set it if required
        try:
            remote_url = self.get_remote_url()
        except ValueError as error:
            gitwrapper.exit_with_error(str(error))
        #
        # 2. Check for the credential.helper config
        if not self.options.ignore_missing_credential_helper:
            if remote_url.startswith('http') and not self.git.config.get(
                    'credential.helper', exit_on_error=False, scope=None):
                gitwrapper.exit_with_error(
                    'The credential.helper git option is not set.\n'
                    'With HTTP based remotes, it is strongly advised'
                    ' to use it,\n'
                    'otherwise you might end up answering username'
                    ' and password questions repeatedly.\n'
                    'Set that git option or specify the script option\n'
                    '  --ignore-missing-credential-helper\n'
                    'to bypass this check.')
            #
        #
        # 3. Push branches
        branch_result = self.push_branches()
        if branch_result:
            logging.error('-' * 72)
            if not self.branches_pushed:
                gitwrapper.exit_with_error('All branch pushes failed!')
            #
            if self.options.fail_fast:
                logging.error('Not all branches could be pushed.')
                self.show_branches_statistics()
                logging.error('-' * 72)
                gitwrapper.exit_with_error(
                    'Run this script again without the --fail-fast option\n'
                    'to push the tags')
            #
        #
        # 4. Push tags
        tags_result = self.push_tags()
        #
        # 5. Output results
        logging.info('-' * 72)
        self.show_branches_statistics()
        self.show_tags_statistics()
        #
        logging.info('-' * 72)
        finish_time = datetime.datetime.now()
        logging.info(
            '%s %s finished at %s',
            SCRIPT_NAME,
            VERSION,
            finish_time)
        duration = (finish_time - start_time).total_seconds()
        logging.info('Elapsed time: %d seconds', duration)
        return tags_result

    def get_remote_url(self):
        """Get the remote URL either from the preconfigured remote
        or from the --set-origin option
        """
        configured_push_urls = {}
        for line in self.git.remote('--verbose',
                                    exit_on_error=False).splitlines():
            try:
                remote_name, url, scope = line.split()
            except ValueError:
                continue
            #
            if scope == '(push)':
                configured_push_urls[remote_name] = url
            #
        #
        specified_url = self.options.set_origin
        origin_url = configured_push_urls.get(ORIGIN)
        if specified_url and origin_url:
            if origin_url == specified_url:
                logging.info('Using preconfigured URL %s', origin_url)
                return origin_url
            #
            raise ValueError(
                'A different URL is already preconfigured for'
                f' {ORIGIN}:\n  {origin_url}\n'
                'If you want tu use that one,'
                ' omit the --set-origin option.\n',
                'Otherwise, remove the existing remote and try again.')
        #
        if specified_url:
            logging.info('Configuring URL %s for %s', specified_url, ORIGIN)
            self.git.remote('add', ORIGIN, specified_url)
            return specified_url
        #
        if origin_url:
            logging.info('Using preconfigured URL %s', origin_url)
            return origin_url
        #
        raise ValueError(
            f'No remote URL for {ORIGIN} preconfigured and none specified.\n'
            'Please specify a remote URL with --set-origin!')

    def get_commit_log(self, commit_id):
        """Return a formatted commit log entry in a form like:

        b9199bd2db8a74daf1115e031c10492f2bc83523
        Commit author: author name <email address>
        Commit time:   2021-08-09 18:34:25 +0200
        Added the skeleton of the push_all script (#16)

        (to be printed for the commit on which a push of a branch finally
         failed)
        """
        return self.git.log(
            '-n', '1',
            '--pretty=format:%H%n'
            'Commit author: %an <%ae>%nCommit time:   %ci%n%s',
            commit_id)

    def get_commit_id_before_head(self, offset=0):
        """Return the id (hash) of the commit
        that was offset (a positive number) commits before HEAD
        """
        if not isinstance(offset, int) or offset < 0:
            raise ValueError('Offset must be a non-negative integer!')
        #
        arguments = ['-n', '1', '--first-parent', '--pretty=format:%H']
        if offset:
            arguments.append(f'--skip={offset}')
        return self.git.log(*arguments)

    def find_branches(self):
        """Yield local branches,
        taking care to ignore console color codes and ignoring the
        '*' character used to indicate the currently selected branch.
        """
        for branch in self.git.branch('--list', '--no-color').splitlines():
            branch = branch.replace('*', '').strip()
            if branch:
                yield branch
            #
        #

    def push_branches(self):
        """Push all branches.

        Return RETURNCODE_OK if everything went fine,
        or RETURNCODE_ERROR on any errors
        """
        # Determine a list of local branches.
        # Put branches with a name in one of the default branch names
        # in front.
        default_branches = []
        remaining_branches = []
        for current_branch in self.find_branches():
            if current_branch in DEFAULT_BRANCH_NAMES:
                default_branches.append(current_branch)
            else:
                remaining_branches.append(current_branch)
            #
        #
        self.all_branches = default_branches + remaining_branches
        self.branches_failed.clear()
        self.branches_pushed.clear()
        if self.options.maximum_batch_size:
            # push branches one by one in batches of maximum batch size
            highest_returncode = RETURNCODE_OK
            for current_branch in self.all_branches:
                push_returncode = self.push_single_branch(
                    current_branch,
                    maximum_batch_size=self.options.maximum_batch_size)
                if push_returncode and self.options.fail_fast:
                    return push_returncode
                #
                highest_returncode = max(push_returncode, highest_returncode)
            #
            return highest_returncode
        #
        push_returncode = self.git.push(
            '-u', 'origin', '--all', exit_on_error=False)
        if push_returncode:
            self.branches_failed = dict.fromkeys(
                self.all_branches, '(global push failed)')
        else:
            self.branches_pushed = self.all_branches
        #
        return push_returncode

    def push_single_branch(self,
                           branch_name,
                           maximum_batch_size=DEFAULT_MAX_BATCH_SIZE):
        """Push commits of a single branch.
        Try committing maximum_batch_size commits first,
        but half the batch size on each failure.
        If the batch size cannot be reduced any further,
        return the last returncode.

        Adapted from <https://stackoverflow.com/a/51468389>.
        """
        logging.info('Switching to branch %r', branch_name)
        self.git.checkout(branch_name)
        remote_branch = f'{ORIGIN}/{branch_name}'
        if self.git.showref_rc(
                '--quiet', '--verify', f'refs/remotes/{remote_branch}',
                exit_on_error=False) > RETURNCODE_OK:
            logging.info(
                'Branch does not exist yet on origin, pushing all commits…')
            commits_range = 'HEAD'
        else:
            logging.info(
                'Branch already exists on origin,'
                ' so pushing missing commits only…')
            commits_range = f'{remote_branch}..HEAD'
        #
        number_to_push = len(
            self.git.log(
                '--first-parent',
                '--pretty=format:x',
                commits_range,
                log_output=False).splitlines())
        #
        logging.info(
            '%s commits to be pushed in %r',
            number_to_push,
            branch_name)
        push_returncode = RETURNCODE_OK
        last_offset = number_to_push
        batch_size = maximum_batch_size
        pushed_commits = 0
        while last_offset:
            if batch_size > last_offset:
                batch_size = last_offset
            #
            commit_id = self.get_commit_id_before_head(
                offset=last_offset - batch_size)
            logging.info(
                'Trying to push %s commits (up to %s)…',
                batch_size, commit_id)
            push_returncode = self.git.push(
                ORIGIN, f'{commit_id}:refs/heads/{branch_name}',
                exit_on_error=False)
            if push_returncode:
                logging.info('… failed')
                if batch_size > 1:
                    logging.info('Reducing batch size.')
                    batch_size = batch_size // 2
                else:
                    logging.error(
                        'Pushing branch %r failed at commit %s',
                        branch_name,
                        commit_id)
                    logging.error(
                        '(%s of %s commits pushed successfully before)',
                        pushed_commits,
                        number_to_push)
                    self.branches_failed[branch_name] = self.get_commit_log(
                        commit_id)
                    return push_returncode
                #
            else:
                last_offset = last_offset - batch_size
                pushed_commits += batch_size
                logging.info('… ok')
                # Double batch size (up to maximum)
                new_batch_size = batch_size * 2
                if new_batch_size > maximum_batch_size:
                    new_batch_size = maximum_batch_size
                #
                if new_batch_size > batch_size:
                    logging.info('Increasing batch size again.')
                    batch_size = new_batch_size
                #
            #
        #
        logging.info('Pushed branch %r:', branch_name)
        logging.info(
            '%s of %s commits have been pushed successfully.',
            pushed_commits,
            number_to_push)
        self.branches_pushed.append(branch_name)
        return push_returncode

    def push_tags(self):
        """Push all tags.

        Return RETURNCODE_OK if everything went fine,
        or RETURNCODE_ERROR on any errors
        """
        self.all_tags = self.git.tag('--list').splitlines()
        self.tags_failed.clear()
        if self.options.maximum_batch_size:
            # push tags one by one
            highest_returncode = RETURNCODE_OK
            for current_tag in self.all_tags:
                tagref = f'refs/tags/{current_tag}'
                push_returncode = self.git.push(
                    ORIGIN, f'{tagref}:{tagref}',
                    exit_on_error=False)
                if push_returncode:
                    self.tags_failed.append(current_tag)
                #
                highest_returncode = max(push_returncode, highest_returncode)
            #
            return highest_returncode
        #
        push_returncode = self.git.push(
            '-u', 'origin', '--tags', exit_on_error=False)
        if push_returncode:
            self.tags_failed = self.all_tags
        #
        return push_returncode

    def show_branches_statistics(self):
        """Show statistics for branches"""
        total = len(self.all_branches)
        failed = len(self.branches_failed)
        successful = len(self.branches_pushed)
        omitted = total - successful - failed
        logging.info('---- Branches summary ----')
        logging.info(
            '%s of %s pushed successfully, %s failed',
            successful, total, failed)
        if omitted:
            logging.info('%s branches omitted', omitted)
        #
        for branch in self.all_branches:
            try:
                failed_commit = self.branches_failed[branch]
            except KeyError:
                if branch in self.branches_pushed:
                    logging.info(' - %s pushed successfully', branch)
                else:
                    logging.info(
                        ' - %s not pushed due to previous errors', branch)
                #
                continue
            #
            logging.error(' - %s push failed at commit:', branch)
            for line in failed_commit.splitlines():
                logging.error('     %s', line)
            #
        #

    def show_tags_statistics(self):
        """Show statistics for tags"""
        total = len(self.all_tags)
        failed = len(self.tags_failed)
        successful = total - failed
        logging.info('---- Tags summary ----')
        logging.info(
            '%s of %s pushed successfully, %s failed',
            successful, total, failed)
        for tag in self.all_tags:
            if tag in self.tags_failed:
                logging.info(' - %s push failed', tag)
            else:
                logging.info(' - %s pushed successfully', tag)
            #
        #


#
# Functions
#


def __get_arguments():
    """Parse command line arguments"""
    argument_parser = argparse.ArgumentParser(
        description='Push the contents of a local Git repository'
        ' to its origin URL')
    argument_parser.set_defaults(loglevel=logging.INFO)
    argument_parser.add_argument(
        '-v', '--verbose',
        action='store_const',
        const=logging.DEBUG,
        dest='loglevel',
        help='Output all messages including debug level')
    argument_parser.add_argument(
        '--set-origin',
        metavar='GIT_URL',
        help='URL to push to (if omitted,'
        ' the existing URL for origin will be used).')
    argument_parser.add_argument(
        '--incremental',
        dest='maximum_batch_size',
        metavar='MAXIMUM_BATCH_SIZE',
        nargs='?',
        type=int,
        const=DEFAULT_MAX_BATCH_SIZE,
        help='If the upstream repository rejects a global'
        ' (i.e. non-incremental) push with the message'
        ' "fatal: pack exceeds maximum allowed size",'
        ' use this option to push the repository contents'
        ' in smaller batches of maximum %(metavar)s'
        ' commits (default: %(const)s).'
        ' During the incremental push, the (effective) batch size'
        ' will be adjusted automatically in the range between 1'
        ' and %(metavar)s, depending on the success or failure of pushes.')
    argument_parser.add_argument(
        '--fail-fast',
        action='store_true',
        help='Exit directly after the first branch failed to be pushed.')
    argument_parser.add_argument(
        '--ignore-missing-credential-helper',
        action='store_true',
        help='Ignore (the lack of) the credential.helper git option.')
    arguments = argument_parser.parse_args()
    if arguments.maximum_batch_size < 0:
        gitwrapper.exit_with_error(
            'Invalid batch size %s!', arguments.maximum_batch_size)
    #
    logging.basicConfig(format=MESSAGE_FORMAT_WITH_LEVELNAME,
                        level=arguments.loglevel)
    #
    return arguments


def main(arguments):
    """Main routine, calling functions from above as required.
    Returns a returncode which is used as the script's exit code.
    """
    full_push = FullPush(arguments)
    return full_push.run()


if __name__ == '__main__':
    # Call main() with the provided command line arguments
    # and exit with its returncode
    sys.exit(main(__get_arguments()))


# vim: fileencoding=utf-8 sw=4 ts=4 sts=4 expandtab autoindent syntax=python:
