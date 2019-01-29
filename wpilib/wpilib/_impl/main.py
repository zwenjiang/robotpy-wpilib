# novalidate

import argparse
import atexit
import inspect
import os
import sys

from os.path import exists
from pkg_resources import iter_entry_points

from .logconfig import configure_logging
import hal_impl

# Make silly mistakes more obvious
_show_run_warning = True


def _atexit():
    if _show_run_warning and not "pytest" in sys.modules:
        print("ERROR: robot program exited without calling wpilib.run! To fix this,")
        print("add the following to your robot.py:")
        print("")
        print('    if __name__ == "__main__":')
        print("        wpilib.run(MyRobot)")
        print()


def _excepthook(*args):
    global _show_run_warning
    _show_run_warning = False
    sys.excepthook = _orig_excepthook
    _orig_excepthook(*args)


_orig_excepthook = sys.excepthook
sys.excepthook = _excepthook

atexit.register(_atexit)


def _log_versions():
    import wpilib
    import hal
    import hal_impl

    import logging

    logger = logging.getLogger("wpilib")

    logger.info("WPILib version %s", wpilib.__version__)
    logger.info(
        "HAL base version %s; %s platform version %s",
        hal.__version__,
        hal_impl.__halplatform__,
        hal_impl.__version__,
    )
    if hasattr(hal_impl.version, "__hal_version__"):
        logger.info("HAL library version %s", hal_impl.version.__hal_version__)

    # should we just die here?
    if (
        hal.__version__ != wpilib.__version__
        and hal.__version__ != hal_impl.__version__
    ):
        logger.warning(
            "Core component versions are not identical! This is not a supported configuration, and you may run into errors!"
        )

    if hal.isSimulation():
        logger.info("Running with simulated HAL.")

        # check to see if we're on a RoboRIO
        # NOTE: may have false positives, but it should work well enough
        if exists("/etc/natinst/share/scs_imagemetadata.ini"):
            logger.warning(
                "Running simulation HAL on actual roboRIO! This probably isn't what you want, and will probably cause difficult-to-debug issues!"
            )

    # Log third party versions
    # -> TODO: in the future, expand 3rd party HAL support here?
    for entry_point in iter_entry_points(group="robotpylib", name=None):
        # Don't actually load the entry points -- just print the
        # packages unless we need to load them
        dist = entry_point.dist
        logger.info("%s version %s", dist.project_name, dist.version)


def _enable_faulthandler():
    #
    # In the event of a segfault, faulthandler will dump the currently
    # active stack so you can figure out what went wrong.
    #
    # Additionally, on non-Windows platforms we register a SIGUSR2
    # handler -- if you send the robot process a SIGUSR2, then
    # faulthandler will dump all of your current stacks. This can
    # be really useful for figuring out things like deadlocks.
    #

    import logging

    logger = logging.getLogger("faulthandler")

    try:
        # These should work on all platforms
        import faulthandler

        faulthandler.enable()
    except Exception as e:
        logger.warn("Could not enable faulthandler: %s", e)
        return

    try:
        import signal

        faulthandler.register(signal.SIGUSR2)
        logger.info("registered SIGUSR2 for PID %s", os.getpid())
    except Exception:
        return


class _CustomHelpAction(argparse.Action):
    def __init__(
        self,
        option_strings,
        dest=argparse.SUPPRESS,
        default=argparse.SUPPRESS,
        help=None,
    ):
        super(_CustomHelpAction, self).__init__(
            option_strings=option_strings,
            dest=dest,
            default=default,
            nargs=0,
            help=help,
        )

    def __call__(self, parser, namespace, values, option_string=None):
        parser.print_help()
        parser.exit(1)  # argparse uses an exit code of zero by default


argparse._HelpAction = _CustomHelpAction


def run(robot_class, **kwargs):
    """
        This function gets called in robot.py like so::

            if __name__ == '__main__':
                wpilib.run(MyRobot)

        This function loads available entry points, parses arguments, and
        sets things up specific to RobotPy so that the robot can run. This
        function is used whether the code is running on the roboRIO or
        a simulation.

        :param robot_class: A class that inherits from :class:`.RobotBase`
        :param **kwargs: Keyword arguments that will be passed to the executed entry points
        :returns: This function should never return
    """

    global _show_run_warning
    _show_run_warning = False

    # sanity check
    if not hasattr(robot_class, "main"):
        print(
            "ERROR: run() must be passed a robot class that inherits from RobotBase (or IterativeBase/SampleBase)"
        )
        exit(1)

    parser = argparse.ArgumentParser()
    subparser = parser.add_subparsers(dest="command", help="commands")
    subparser.required = True

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Enable debug logging",
    )

    parser.add_argument(
        "--ignore-plugin-errors",
        action="store_true",
        default=False,
        help="Ignore errors caused by RobotPy plugins (probably should fix or replace instead!)",
    )

    has_cmd = False

    for entry_point in iter_entry_points(group="robotpy", name=None):
        try:
            cmd_class = entry_point.load()
        except ImportError:
            if "--ignore-plugin-errors" in sys.argv:
                print("WARNING: Ignoring error in '%s'" % entry_point)
                continue
            else:
                print(
                    "Plugin error detected in '%s' (use --ignore-plugin-errors to ignore this)"
                    % entry_point
                )
                raise

        cmdparser = subparser.add_parser(
            entry_point.name, help=inspect.getdoc(cmd_class)
        )
        obj = cmd_class(cmdparser)
        cmdparser.set_defaults(cmdobj=obj)
        has_cmd = True

    if not has_cmd:
        parser.error(
            "No entry points defined -- robot code can't do anything. Install packages to add entry points (see README)"
        )
        exit(1)

    options = parser.parse_args()

    configure_logging(options.verbose)

    _log_versions()
    _enable_faulthandler()

    retval = options.cmdobj.run(options, robot_class, **kwargs)

    if retval is None:
        retval = 0
    elif retval is True:
        retval = 0
    elif retval is False:
        retval = 1

    exit(retval)
