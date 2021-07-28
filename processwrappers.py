# -*- coding: utf-8 -*-

"""

processwrappers

Convenience wrappers around the subprocess module functionality

Copyright (C) 2020-2021 Rainer Schwarzbach

License: MIT, see LICENSE file

"""


import logging
import re
import shlex
import subprocess
import sys
import threading
import time

from queue import Queue


#
# Constants
#


SUBPROCESS_DEFAULTS = dict(
    close_fds=True,
    stderr=subprocess.PIPE,
    stdout=subprocess.PIPE)

if sys.platform == 'win32':
    del SUBPROCESS_DEFAULTS['close_fds']
#


#
# Classes
#


class AsynchronousStreamReader(threading.Thread):
    """Helper class to implement asynchronous reading of a stream
    in a separate thread. Pushes read lines on a queue to
    be consumed in another thread.

    Adapted from <https://github.com/soxofaan/asynchronousfilereader>
    """

    def __init__(self, stream, autostart=True):
        self._stream = stream
        self.queue = Queue()
        threading.Thread.__init__(self)
        if autostart:
            self.start()
        #

    def run(self):
        """The body of the thread:
        read lines and put them on the queue.
        """
        while True:
            time.sleep(0)
            line = self._stream.readline()
            if not line:
                break
            self.queue.put(line)
        #

    def eof(self):
        """Check whether there is no more content to expect."""
        return not self.is_alive() and self.queue.empty()

    def readlines(self):
        """Get currently available lines."""
        while not self.queue.empty():
            yield self.queue.get()
        #


#
# Functions
#


def future_shlex_join(sequence):
    """Simple replacement for the shlex.join() function
    that was introduced in Python 3.8
    """
    output_sequence = []
    for item in sequence:
        if re.search(r'\s', item):
            output_sequence.append(repr(item))
        else:
            output_sequence.append(item)
        #
    #
    return ' '.join(output_sequence)


def __prepare_command(command, **kwargs):
    """Return a command prepared for subprocess.run()
    and subprocess.Popen(), along with the keyword arguments,
    except loglevel.

    Keyword arguments:
        * all subprocess.run() resp. subprocess.Popen() arguments
        * loglevel: the loglevel for logging the command line
          (defaults to logging.INFO)
    """
    if isinstance(command, str):
        logging.warning(
            'Converting command %r given as a string into a list',
            command)
        converted_command = shlex.split(command)
    else:
        # Convert all command components to strings
        converted_command = [str(argument) for argument in command]
    #
    loglevel = kwargs.pop('loglevel', None)
    if loglevel:
        logging.log(
            loglevel,
            'Executing command: %s',
            future_shlex_join(converted_command))
    #
    return converted_command, kwargs


def get_command_result(command, check=True, **kwargs):
    """Return the result from the specified command,
    i.e. a subprocess.CompletedProcess instance as returned
    by subprocess.run()

    Keyword arguments:
        * all subprocess.run() arguments
          (with deviant defaults as in SUBPROCESS_DEFAULTS),
        * loglevel: the loglevel for logging the command line
          (defaults to logging.INFO)
    """
    command_keyword_arguments = dict(SUBPROCESS_DEFAULTS)
    converted_command, kwargs = __prepare_command(command, **kwargs)
    command_keyword_arguments.update(kwargs)
    return subprocess.run(
        converted_command, check=check, **command_keyword_arguments)


def get_streams_and_process(command, **kwargs):
    """Start a subprocess using subprocess.Popen().
    Return a dict containing an Asynchronous StreamReader
    instance for each output stream that was specified
    (named like the stream: stderr or stdout),
    and the Popen instance as process.
    """
    converted_command, kwargs = __prepare_command(command, **kwargs)
    available_streams = ('stderr', 'stdout')
    streams_to_read = []
    for stream_name in available_streams:
        current_stream = kwargs.pop(stream_name, None)
        if current_stream == AsynchronousStreamReader:
            streams_to_read.append(stream_name)
            kwargs[stream_name] = subprocess.PIPE
        else:
            kwargs[stream_name] = current_stream
        #
    #
    started_process = subprocess.Popen(converted_command, **kwargs)
    process_info = dict(process=started_process)
    for stream_name in streams_to_read:
        process_info[stream_name] = AsynchronousStreamReader(
            getattr(started_process, stream_name))
    #
    return process_info


def long_running_process_result(command,
                                check=True,
                                stderr_loglevel=logging.ERROR,
                                stdout_loglevel=logging.INFO,
                                all_to_stdout=False,
                                output_encoding='UTF-8',
                                **kwargs):
    """Blueprint for handling long-running processes:
    Log stdout using stdout_loglevel and stderr using stderr_loglevel,
    both while the process is running.
    Return a CompletedProcess instance or raise a CalledProcessError
    if check is True (the default) and the returncode is non-zero.
    If all_to_stdout ist set True, redirect stderr to stdout.

    Also adapted from
    <https://github.com/soxofaan/asynchronousfilereader>
    """
    kwargs['stderr'] = AsynchronousStreamReader
    kwargs['stdout'] = AsynchronousStreamReader
    if sys.platform != 'win32':
        kwargs['close_fds'] = True
    #
    process_info = get_streams_and_process(command, **kwargs)
    process = process_info['process']
    stdout_reader = process_info['stdout']
    stderr_reader = process_info['stderr']
    collected_stdout = []
    if all_to_stdout:
        collected_stderr = collected_stdout
    else:
        collected_stderr = []
    #
    while not stdout_reader.eof() or not stderr_reader.eof():
        # Show what has been received from stderr and stdout,
        # then sleep a short time before polling again
        for line in stderr_reader.readlines():
            collected_stderr.append(line)
            logging.log(
                stderr_loglevel, line.decode(output_encoding).rstrip())
        #
        for line in stdout_reader.readlines():
            collected_stdout.append(line)
            logging.log(
                stdout_loglevel, line.decode(output_encoding).rstrip())
        time.sleep(.1)
    # Cleanup:
    # Wait for the threads to end and close the file descriptors
    stderr_reader.join()
    stdout_reader.join()
    process.stderr.close()
    process.stdout.close()
    # Construct and return the result
    stdout_data = b''.join(collected_stdout)
    if all_to_stdout:
        stderr_data = None
    else:
        stderr_data = b''.join(collected_stderr)
    #
    completed_process = subprocess.CompletedProcess(
        args=process.args,
        returncode=process.wait(),
        stdout=stdout_data,
        stderr=stderr_data)
    if check:
        completed_process.check_returncode()
    #
    return completed_process


# vim: fileencoding=utf-8 sw=4 ts=4 sts=4 expandtab autoindent syntax=python:
