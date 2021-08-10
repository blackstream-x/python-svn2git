# -*- coding: utf-8 -*-

"""

gitwrapper.py

Wrapper around various git subcommands

Copyright (C) 2020-2021 Rainer Schwarzbach

License: MIT, see LICENSE file

"""


import datetime
import logging
import subprocess
import sys

# local module

import processwrappers


#
# Constants
#


RETURNCODE_OK = 0
RETURNCODE_ERROR = 1

# Default Git executable
DEFAULT_GIT = 'git'

# 'git config' scopes
CONFIG_GLOBAL = '--global'
CONFIG_LOCAL = '--local'


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
    logging.info('Script aborted at %s', datetime.datetime.now())
    sys.exit(RETURNCODE_ERROR)


def process_error_data(error):
    """Return data from a CalledProcessError as a single string"""
    lines = [
        '[Command failed] %s' % processwrappers.future_shlex_join(error.cmd),
        'Returncode: %s' % error.returncode]
    if error.stderr:
        lines.append('___ Standard error ___')
        lines.extend(error.stderr.decode().splitlines())
    #
    if error.stdout:
        lines.append('___ Standard output ___')
        lines.extend(error.stdout.decode().splitlines())
    #
    return '\n'.join(lines)


def get_command_result(*command, exit_on_error=True, **kwargs):
    """Run the specified command and return its result
    (i.e. a subprocess.CompletedProcess instance).
    If "exit_on_error" is set True (the default),
    the calling script will exit with an error mesage
    if the command returncode is non-zero.
    """
    kwargs.update(
        dict(check=exit_on_error))
    try:
        result = processwrappers.get_command_result(command, **kwargs)
    except subprocess.CalledProcessError as error:
        exit_with_error(process_error_data(error))
    #
    return result


def get_command_output(*command, **kwargs):
    """Run the specified command and return its output
    (stdout and stderr combined).
    """
    kwargs.update(
        dict(stdout=subprocess.PIPE,
             stderr=subprocess.PIPE,
             loglevel=logging.DEBUG))
    command_result = get_command_result(*command, **kwargs)
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


def get_command_returncode(*command, **kwargs):
    """Run the specified (probably long running)
    command and return its returncode.
    The output streams (stdout and stderr) are not captured,
    allowing normal user interaction with the command
    (eg. for password input).
    """
    kwargs.update(
        dict(stderr=None,
             stdout=None,
             loglevel=logging.INFO))
    return get_command_result(*command, **kwargs).returncode


#
# Classes
#


class BaseGitWrapper:

    """Wrapper for git command execution, base class"""

    def __init__(self,
                 env=None,
                 git_command=DEFAULT_GIT):
        """Set the internal env and git_command attributes"""
        self.env = env
        self.git_command = git_command

    def get_output(self, *arguments, **kwargs):
        """Run git with the specified arguments
        and return its output (stdout and stderr) combined.
        """
        kwargs.update(
            dict(stdout=subprocess.PIPE,
                 stderr=subprocess.PIPE,
                 loglevel=logging.DEBUG))
        kwargs.setdefault('env', self.env)
        command_result = get_command_result(
            self.git_command, *arguments, **kwargs)
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


class GitConfigWrapper(BaseGitWrapper):

    """Wrapper for a subset of possible git config calls:
    git config [ --global | --local ] <key> <value>
    git --get [ --global | --local ] <key>
    git --unset [ --global | --local ] <key>

    The --global or --local option is passed via scope
    and always defaults to --local.
    """

    long_option_prefix = '--'

    def __init__(self,
                 env=None,
                 git_command=DEFAULT_GIT,
                 local_config_enabled=True):
        """Set the internal __env, __git_command,
        and __local_config_enabled attributes
        """
        super().__init__(env=env, git_command=git_command)
        self.__local_config_enabled = local_config_enabled

    def __check_key(self, key):
        """Prevent programming errors:
        raise a ValueError if key starts with '--'
        """
        if key.startswith(self.long_option_prefix):
            raise ValueError('Invalid key for git config: %r!' % key)
        #

    def __execute(self, *args, scope=CONFIG_LOCAL, **kwargs):
        """Execute the 'git config' command.
        If scope is set to None explicitly, the preferred scope
        (--local) is omitted
        """
        subcommand = ['config']
        if scope == CONFIG_GLOBAL or (
                scope == CONFIG_LOCAL and self.__local_config_enabled):
            subcommand.append(scope)
        #
        kwargs.setdefault('env', self.env)
        return self.get_output(*subcommand, *args, **kwargs)

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


class GitWrapper(BaseGitWrapper):

    """Wrapper for a subset of possible git commands.
    The .config instance attribute
    is set to a GitConfigWrapper instance.
    """

    def __init__(self,
                 env=None,
                 git_command=DEFAULT_GIT,
                 local_config_enabled=True):
        """Set the internal __env, and __git_command attributes,
        plus the config wrapper
        """
        super().__init__(env=env, git_command=git_command)
        self.config = None
        self.set_config(local_config_enabled=local_config_enabled)

    def set_config(self, local_config_enabled=True):
        """Set the config wrapper"""
        self.config = GitConfigWrapper(
            env=self.env,
            git_command=self.git_command,
            local_config_enabled=local_config_enabled)

    def get_returncode(self, *arguments, **kwargs):
        """Run git with the specified arguments
        and return the process returncode.
        The output streams (stdout and stderr) are not captured,
        allowing normal user interaction with the command
        (eg. for password input).
        """
        kwargs.update(
            dict(stdout=None,
                 stderr=None,
                 loglevel=logging.INFO))
        kwargs.setdefault('env', self.env)
        command_result = get_command_result(
            self.git_command, *arguments, **kwargs)
        return command_result.returncode

    # Commands returning only the returncode

    def gc_(self, *arguments, **kwargs):
        """git gc + arguments
        Passthru output and return returncode
        """
        return self.get_returncode('gc', *arguments, **kwargs)

    def push(self, *arguments, **kwargs):
        """git push + arguments
        Passthru output and return returncode
        """
        return self.get_returncode('push', *arguments, **kwargs)

    def showref(self, *arguments, **kwargs):
        """git show-ref + arguments
        Passthru output and return returncode
        """
        return self.get_returncode('show-ref', *arguments, **kwargs)

    def svn_fetch(self, *arguments, **kwargs):
        """git svn fetch + arguments
        Passthru output and return returncode
        """
        return self.get_returncode('svn', 'fetch', *arguments, **kwargs)

    def svn_init(self, *arguments, **kwargs):
        """git svn init + arguments
        Passthru output and return returncode
        """
        return self.get_returncode('svn', 'init', *arguments, **kwargs)

    # Commands returning output

    def branch(self, *arguments, **kwargs):
        """git branch + arguments
        Capture stderr and stdout and return them combined
        """
        return self.get_output('branch', *arguments, **kwargs)

    def checkout(self, *arguments, **kwargs):
        """git checkout + arguments
        Capture stderr and stdout and return them combined
        """
        return self.get_output('checkout', *arguments, **kwargs)

    def log(self, *arguments, **kwargs):
        """git log + arguments
        Capture stderr and stdout and return them combined
        """
        return self.get_output('log', *arguments, **kwargs)

    def rebase(self, *arguments, **kwargs):
        """git rebase + arguments
        Capture stderr and stdout and return them combined
        """
        return self.get_output('rebase', *arguments, **kwargs)

    def remote(self, *arguments, **kwargs):
        """git remote + arguments
        Capture stderr and stdout and return them combined
        """
        return self.get_output('remote', *arguments, **kwargs)

    def status(self, *arguments, **kwargs):
        """git status + arguments
        Capture stderr and stdout and return them combined
        """
        return self.get_output('status', *arguments, **kwargs)

    def tag(self, *arguments, **kwargs):
        """git tag + arguments
        Capture stderr and stdout and return them combined
        """
        return self.get_output('tag', *arguments, **kwargs)


# vim: fileencoding=utf-8 sw=4 ts=4 sts=4 expandtab autoindent syntax=python:
