# -*- coding: utf-8 -*-

"""

processwrappers

Convenience wrappers around the subprocess module functionality

Copyright (C) 2021 Rainer Schwarzbach

License: MIT, see LICENSE file

"""


import logging
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


class Namespace(dict):

    """A dict subclass that exposes its items as attributes.

    Adapted from:
    ActiveState Code » Recipes » A Simple Namespace Class (Python recipe)
    <http://code.activestate.com/recipes/577887-a-simple-namespace-class/>

    Warning: Namespace instances only have direct access to the
    attributes defined in the visible_attributes tuple
    """

    visible_attributes = ('items', )

    def __repr__(self):
        """Object representation"""
        return '{0}({1})'.format(
            type(self).__name__,
            super(Namespace, self).__repr__())

    def __dir__(self):
        """Members sequence"""
        return tuple(self)

    def __getattribute__(self, name):
        """Access a visible attribute
        or return an existing dict member
        """
        if name in type(self).visible_attributes:
            return object.__getattribute__(self, name)
        #
        try:
            return self[name]
        except KeyError:
            raise AttributeError(
                '{0!r} object has no attribute {1!r}'.format(
                    type(self).__name__, name))
        #

    def __setattr__(self, name, value):
        """Set an attribute"""
        self[name] = value

    def __delattr__(self, name):
        """Delete an attribute"""
        del self[name]


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


def get_command_result(command, **kwargs):
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
    return subprocess.run(converted_command, **command_keyword_arguments)


def get_streams_and_process(command, **kwargs):
    """Start a subprocess using subprocess.Popen().
    Return a namespace containing an Asynchronous StreamReader
    instance for each output stream that was specified
    (named like the stream: stderr or stdout),
    and the Popen instnace as process.
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
    process_info = Namespace(
        process=subprocess.Popen(converted_command, **kwargs))
    for stream_name in streams_to_read:
        process_info[stream_name] = AsynchronousStreamReader(
            getattr(process_info.process, stream_name))
    #
    return process_info


def long_running_process_result(*arguments,
                                encoding='UTF-8',
                                **kwargs):
    """Return the returncode from the provided command.
    Log stdout output using logging.info,
    and stderr output using logging.error,
    both while the process is running.
    Prefix all log lines with <log_line_prefix> if provided.
    """
    kwargs['stderr'] = AsynchronousStreamReader
    kwargs['stdout'] = AsynchronousStreamReader
    if sys.platform != 'win32':
        kwargs['close_fds'] = True
    #
    process_info = get_streams_and_process(arguments, **kwargs)
    while not process_info.stdout.eof() or not process_info.stderr.eof():
        # Show what we received from standard error.
        for line in process_info.stderr.readlines():
            stderr_line = line.decode(encoding).rstrip()
            logging.error(stderr_line)
            #
        # Show what we received from standard output.
        for line in process_info.stdout.readlines():
            stdout_line = line.decode(encoding).rstrip()
            logging.info(stdout_line)
        # Sleep a bit before polling the readers again.
        time.sleep(.1)
    # Be tidy and join the threads we started.
    process_info.stdout.join()
    process_info.stderr.join()
    # Close subprocess' file descriptors.
    process_info.process.stdout.close()
    process_info.process.stderr.close()
    # Return the process' returncode
    return process_info.process.wait()

  
# vim: fileencoding=utf-8 sw=4 ts=4 sts=4 expandtab autoindent syntax=python:  
