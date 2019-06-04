# DExTer : Debugging Experience Tester
# ~~~~~~   ~         ~~         ~   ~~
#
# Copyright (c) 2018 by SN Systems Ltd., Sony Interactive Entertainment Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
"""Discover potential/available debugger interfaces."""

from collections import OrderedDict
import imp
import inspect
import os
import pickle
import subprocess
import sys
from tempfile import NamedTemporaryFile

from dex.command import find_all_commands
from dex.debugger.DebuggerBase import DebuggerBase
from dex.dextIR import CommandIR, CommandListIR, DextIR, LocIR
from dex.dextIR.DextIR import importDextIR
from dex.utils import get_root_directory, Timer
from dex.utils.Environment import is_native_windows
from dex.utils.Exceptions import CommandParseError, DebuggerException
from dex.utils.Exceptions import ToolArgumentError
from dex.utils.Warning import warn


def _get_potential_debuggers():  # noqa
    """Search the debugger directory for any classes which are subclasses of
    DebuggerBase and return a dict.
    """
    try:
        return _get_potential_debuggers.cached
    except AttributeError:
        _get_potential_debuggers.cached = {}
        for dir_, _, files in os.walk(os.path.join(os.path.dirname(__file__))):
            potential_modules = [
                os.path.splitext(f)[0] for f in files
                if f.endswith('.py') and not f.startswith('__')
            ]

            for m in potential_modules:
                try:
                    module_info = imp.find_module(m, [dir_])
                    module = imp.load_module(m, *module_info)
                except ImportError:
                    continue

                for _, c in inspect.getmembers(module, inspect.isclass):
                    if issubclass(c, DebuggerBase):
                        try:
                            key = c.get_option_name()
                        except NotImplementedError:
                            continue

                        if key in _get_potential_debuggers.cached:
                            assert (_get_potential_debuggers.cached[
                                key].__name__ == c.__name__), (
                                    key, _get_potential_debuggers.cached[key],
                                    c)
                        else:
                            _get_potential_debuggers.cached[key] = c

        return _get_potential_debuggers.cached


def _warn_meaningless_option(context, option):
    if context.options.list_debuggers:
        return

    warn(context,
         'option <y>"{}"</> is meaningless with this debugger'.format(option),
         '--debugger={}'.format(context.options.debugger))


def add_debugger_tool_arguments1(parser, defaults):
    defaults.lldb_executable = 'lldb.exe' if is_native_windows() else 'lldb'
    parser.add_argument(
        '--lldb-executable',
        type=str,
        metavar='<file>',
        default=None,
        display_default=defaults.lldb_executable,
        help='location of LLDB executable')


def add_debugger_tool_arguments(parser, context, defaults):
    debuggers = Debuggers(context)
    potential_debuggers = sorted(debuggers.potential_debuggers().keys())

    add_debugger_tool_arguments1(parser, defaults)

    parser.add_argument(
        '--debugger',
        type=str,
        choices=potential_debuggers,
        required=True,
        help='debugger to use')
    parser.add_argument(
        '--max-steps',
        metavar='<int>',
        type=int,
        default=1000,
        help='maximum number of program steps allowed')
    parser.add_argument(
        '--pause-between-steps',
        metavar='<seconds>',
        type=float,
        default=0.0,
        help='number of seconds to pause between steps')
    defaults.show_debugger = False
    parser.add_argument(
        '--show-debugger',
        action='store_true',
        default=None,
        help='show the debugger')
    defaults.arch = 'x86_64'
    parser.add_argument(
        '--arch',
        type=str,
        metavar='<architecture>',
        default=None,
        display_default=defaults.arch,
        help='target architecture')


def handle_debugger_tool_options1(context, defaults):  # noqa
    options = context.options

    if options.lldb_executable is None:
        options.lldb_executable = defaults.lldb_executable
    else:
        if getattr(options, 'debugger', 'lldb') != 'lldb':
            _warn_meaningless_option(context, '--lldb-executable')

        options.lldb_executable = os.path.abspath(options.lldb_executable)
        if not os.path.isfile(options.lldb_executable):
            raise ToolArgumentError('<d>could not find</> <r>"{}"</>'.format(
                options.lldb_executable))


def handle_debugger_tool_options(context, defaults):  # noqa
    options = context.options

    handle_debugger_tool_options1(context, defaults)

    if options.arch is None:
        options.arch = defaults.arch
    else:
        if options.debugger != 'lldb':
            _warn_meaningless_option(context, '--arch')

    if options.show_debugger is None:
        options.show_debugger = defaults.show_debugger
    else:
        if options.debugger == 'lldb':
            _warn_meaningless_option(context, '--show-debugger')


def _get_command_infos(context):
    commands = find_all_commands(context.options.source_files)
    command_infos = OrderedDict()
    for command_type in commands:
        for command in commands[command_type].values():
            if command_type not in command_infos:
                command_infos[command_type] = CommandListIR()

            loc = LocIR(path=command.path, lineno=command.lineno, column=None)
            command_infos[command_type].append(
                CommandIR(loc=loc, raw_text=command.raw_text))
    return OrderedDict(command_infos)


def empty_debugger_steps(context):
    return DextIR(
        executable_path=context.options.executable,
        source_paths=context.options.source_files,
        dexter_version=context.version)


def get_debugger_steps(context):
    step_collection = empty_debugger_steps(context)

    with Timer('parsing commands'):
        try:
            step_collection.commands = _get_command_infos(context)
        except CommandParseError as e:
            msg = 'parser error: <d>{}({}):</> {}\n{}\n{}\n'.format(
                e.filename, e.lineno, e.info, e.src, e.caret)
            raise DebuggerException(msg)

    with NamedTemporaryFile(
            dir=context.working_directory.path, delete=False) as fp:
        fp.write(step_collection.as_json.encode('utf-8'))
        json_path = fp.name

    with NamedTemporaryFile(
            dir=context.working_directory.path, delete=False, mode='wb') as fp:
        pickle.dump(context.options, fp, protocol=pickle.HIGHEST_PROTOCOL)
        pickle_path = fp.name

    dexter_py = sys.argv[0]
    if not os.path.isfile(dexter_py):
        dexter_py = os.path.join(get_root_directory(), '..', dexter_py)
    assert os.path.isfile(dexter_py)

    with NamedTemporaryFile(dir=context.working_directory.path) as fp:
        args = [
            sys.executable, dexter_py, 'run-debugger-internal-', json_path,
            pickle_path, '--working-directory', context.working_directory.path,
            '--unittest=off', '--lint=off',
            '--indent-timer-level={}'.format(Timer.indent + 2)
        ]
        try:
            with Timer('running external debugger process'):
                subprocess.check_call(args)
        except subprocess.CalledProcessError as e:
            raise DebuggerException(e)

    with open(json_path, 'r') as fp:
        step_collection = importDextIR(fp.read())

    return step_collection


class Debuggers(object):
    @classmethod
    def potential_debuggers(cls):
        try:
            return cls._potential_debuggers
        except AttributeError:
            cls._potential_debuggers = _get_potential_debuggers()
            return cls._potential_debuggers

    def __init__(self, context):
        self.context = context

    def load(self, key, step_collection=None):
        with Timer('load {}'.format(key)):
            return Debuggers.potential_debuggers()[key](self.context,
                                                        step_collection)

    def _populate_debugger_cache(self):
        debuggers = []
        for key in sorted(Debuggers.potential_debuggers()):
            debugger = self.load(key)

            class LoadedDebugger(object):
                pass

            LoadedDebugger.option_name = key
            LoadedDebugger.full_name = '[{}]'.format(debugger.name)
            LoadedDebugger.is_available = debugger.is_available

            if LoadedDebugger.is_available:
                try:
                    LoadedDebugger.version = debugger.version.splitlines()
                except AttributeError:
                    LoadedDebugger.version = ['']
            else:
                try:
                    LoadedDebugger.error = debugger.loading_error.splitlines()
                except AttributeError:
                    LoadedDebugger.error = ['']

                try:
                    LoadedDebugger.error_trace = debugger.loading_error_trace
                except AttributeError:
                    LoadedDebugger.error_trace = None

            debuggers.append(LoadedDebugger)
        return debuggers

    def list(self):
        debuggers = self._populate_debugger_cache()

        max_o_len = max(len(d.option_name) for d in debuggers)
        max_n_len = max(len(d.full_name) for d in debuggers)

        msgs = []

        for d in debuggers:
            # Option name, right padded with spaces for alignment
            option_name = (
                '{{name: <{}}}'.format(max_o_len).format(name=d.option_name))

            # Full name, right padded with spaces for alignment
            full_name = ('{{name: <{}}}'.format(max_n_len)
                         .format(name=d.full_name))

            if d.is_available:
                name = '<b>{} {}</>'.format(option_name, full_name)

                # If the debugger is available, show the first line of the
                #  version info.
                available = '<g>YES</>'
                info = '<b>({})</>'.format(d.version[0])
            else:
                name = '<y>{} {}</>'.format(option_name, full_name)

                # If the debugger is not available, show the first line of the
                # error reason.
                available = '<r>NO</> '
                info = '<y>({})</>'.format(d.error[0])

            msg = '{} {} {}'.format(name, available, info)

            if self.context.options.verbose:
                # If verbose mode and there was more version or error output
                # than could be displayed in a single line, display the whole
                # lot slightly indented.
                verbose_info = None
                if d.is_available:
                    if d.version[1:]:
                        verbose_info = d.version + ['\n']
                else:
                    # Some of list elems may contain multiple lines, so make
                    # sure each elem is a line of its own.
                    verbose_info = d.error_trace

                if verbose_info:
                    verbose_info = '\n'.join('        {}'.format(l.rstrip())
                                             for l in verbose_info) + '\n'
                    msg = '{}\n\n{}'.format(msg, verbose_info)

            msgs.append(msg)
        self.context.o.auto('\n{}\n\n'.format('\n'.join(msgs)))