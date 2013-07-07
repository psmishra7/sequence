
import time
import logging
import datetime
from threading import Thread
from daytime import DayTime

__version__ = '0.3'

LOGGER = logging.getLogger('sequence')


class Timer:
    """
    Provides timer-facilities regarding to the needs of :class:`Sequence`.
    """
    def __init__(self, interval, max_count=None, snap=False, latency_tolerance=0.01):
        """
        Constructor of Timer.

        :arg float interval:    Interval in seconds.
        :keyword int max_count: maximal number of passes.
        :keyword bool snap:     snaps the sequence into a specific rythm
                                (s. :meth:`start`)
        :keyword float latency_tolerance:
                                defines the limit for a timelag.
        """
        self._interval = interval
        self._snap = snap
        self._max_count = max_count
        self._latency_tolerance = latency_tolerance
        self._stage = None
        self._counter = 0
        self._timelag = None
        self._stopped = False

    @property
    def counter(self):
        """Number of passes through a sequenz."""
        return self._counter

    @property
    def interval(self):
        """interval used for a sequenz (int or float)."""
        return self._interval

    @property
    def timelag(self):
        """
        time a check-call was lagged.

        None if the latency is smaller or equal latency_tolerance.
        """
        return self._timelag

    @property
    def alive(self):
        """True as soon as Timer was started and as long it wasn't stopped."""
        return bool(self._stage)

    @property
    def runtime(self):
        """
        Time the actual pass lasts. None if not :attr:`alive`.

        Mind that this does not mean the seconds since last call to check. The
        check-call actualizes the values whithin a pass, but don't set
        the starting point of it. The starting point is evaluated by
        adding the interval to a staged point of time.
        """
        if self.alive: return time.time() - self._stage
        else: return None

    def actualize(self):
        """
        This is a hook for dynamical evaluation of intervals.

        The initial interval_data will be processed to generate the interval
        and save it as self._interval.
        The method will be called once for each sequence.
        """

    def start(self):
        """
        Start a timer (Set the the starting time).

        If the timer was initialized with snap set to True the starting-time
        will be evaluated depending on the actual interval.
        On that way all sequences running with the same interval will be
        synchronized. Stopped and restarted sequences will snap into the same
        "rhythm".

        :returns:       seconds till the first check-call returns True.
                        This is relevant for a *snapstart*, otherwise it will be
                        ``0``.
        """
        self.actualize()
        self._first_time = True

        if not self._snap:
            self._stage = time.time()
            return 0
        else:
            now = time.time()
            seconds_to_wait = self.interval - now % self.interval
            self._stage = now + seconds_to_wait
            return seconds_to_wait

    def check(self):
        """
        Checks if a new pass has begun.

        :returns:   * True:     if interval has been run down
                    * False:    if a pass still lasts
                    * None:     if a not Timer.alive

        This actualizes also the :attr:`counter`, :attr:`timelag` and
        :attr:`runtime` (which now counts from a new stage on).
        """
        
        # if the timer is not running:
        if not self.alive: return

        # if interval is 0:
        elif not self.interval:
            self.actualize()
            if self.interval: time.sleep(self.start())
            else: return False

        # Because the timer was started outside the loop, the first check
        # must return True.
        elif self._first_time:
            self._counter += 1
            self._first_time = False
            return True

        # actual sequenz hasn't finished yet:
        elif time.time() - self._stage < self._interval: return False

        else:
            lag = self.runtime - self._interval
            self._timelag = None if lag <= self._latency_tolerance else lag

            self.actualize()
            if not self.interval: return False

            self._counter += 1
            self._stage += self.interval
            return True

    def run_check(self):
        """
        Checks if timer has been stopped and max_count has not reached.

        :returns: bool
        """
        if self._stopped: self.reset()
        return self.alive and not self.counter is self._max_count

    def reset(self):
        """Reset the :obj:`Timer`."""
        self._counter = 0
        self._stage = None
        self._stopped = False

    def stop(self):
        """
        :obj:`Timer` will be killed by the next :meth:`run_check`-call.
        """
        self._stopped = True


class DaytimeTimer(Timer):
    """
    Extends :class:`Timer`.
    """
    def __init__(self, data, *args, **kwargs):
        """
        :arg list data:         List of tuples, each with a :obj:`datetime.time`
                                and an :obj:`int` as *interval*. From each
                                :obj:`datetime.time` on the corr. *interval*
                                will be used.
        :keyword int max_count: maximal number of passes.
        :keyword bool snap:     snaps the sequence into a specific rythm
                                (s. :meth:`start`)
        :keyword float latency_tolerance:
                                defines the limit for a timelag.
        """
        self._data = data
        self._data.sort()
        super(DaytimeTimer, self).__init__(self, *args, **kwargs)

    def actualize(self):
        """Actualizes the :attr:`Timer.interval` based on the actual daytime.
        """
        now = DayTime.daytime()
        if now < self._data[-1][0]:
            self._interval = self._data[0][1]
        else:
            for time, interval in self._data:
                if time < now: self._interval = interval


class Sequence:
    """
    Runs several :class:`Cmd`-objects in a repeated sequence.
    """
    def __init__(self, timer, cmds=list()):
        """
        Constructor of Sequenz.

        :arg Timer timer:
        :keyword list cmds:     list of :class:`Cmd`-objects
        """
        self.timer = timer
        self.cmds = cmds

    @property
    def alive(self):
        """
        A :obj:`Sequence` is alive as long as there is a :obj:`Cmd` to run.
        """
        return self._alive

    def add_cmd(self, cmd):
        """
        Add a :obj:`Cmd`-object.
        """
        self.cmds.append(cmd)

    def thread(self, daemon=False):
        """
        Start the main-loop in a :obj:`threading.Thread`.

        :arg bool daemon:   If True the thread will be daemonized.

        .. Notice::
            A daemonized :obj:`threading.Thread` will be interrupted instantly
            by TERM-SIG (and so will all actually processed commands) while a
            not daemonized thread won't be interrupted at all.
            If you wish a sequence that finishes his last pass on TERM-SIG,
            use a not daemonized thread and call :meth:`stop` on catching the
            signal. This causes the thread to end when all commands of the
            lasting pass are processed.
        """
        #FIXME: With a non-daemonized thread the signals won't be catched
        # anymore after a certain while.
        thread = Thread(target=self.go)
        thread.daemon = daemon
        thread.start()

    def stop(self, wait=False):
        """
        Stopps the :obj:`Sequence` after all remaining commands of the lasting
        pass are processed.

        :keyword bool wait:     if True :meth:`stop` returns foremost when the
                                sequence actually finished. (defaults to False)
        """
        self.timer.stop()
        if wait:
            while self.alive: time.sleep(0.01)

    def go(self):
        """
        Start the sequenz as a non-threaded loop.

        On interruption a non-threaded sequence will at least finish processing
        the actual command.
        """
        time.sleep(self.timer.start())
        self._alive = True
        while self.timer.run_check():

            # start a new round
            if self.timer.check():

                # check for a timelag
                if self.timer.timelag:
                    LOGGER.error('TIMELAG: %s sec!' % round(self.timer.timelag, 2))

                LOGGER.info('ROUND {0} (INTERVAL {1})'.format(
                    self.timer.counter, self.timer.interval
                    ))

                threads = list()
                 # loop over cmd-list
                for cmd in self.cmds:
                    if not cmd.check(self): continue
                    thread = Thread(target=cmd, args=[self] + cmd.args, kwargs=cmd.kwargs)
                    thread.start()
                    if cmd.join: thread.join()
                    threads.append(thread)


            time.sleep(0.002)

        else:
            # check if any thread is still alive and wait for it:
            if locals().has_key("threads"):
                while filter(lambda t: t.is_alive(), threads): time.sleep(0.01)

            self.timer.reset()
            self._alive = False
            LOGGER.info('finished')


class BaseCmd(object):
    """
    Base-Class for callables used in a sequence.
    """
    def __init__(self, cmd, args=list(), kwargs=dict(), join=False):
        """
        Constructor of BaseCmd.

        :arg callable cmd:          The callable to run within a sequence.
        :keyword list args:         Arguments to pass to *cmd*.
        :keyword dict kwargs:       Keywords to pass to *cmd*.
        :keyword bool join:         If *cmd* should be called as joined
                                    :obj:`threading.Thread`
        """
        self._cmd = cmd
        self.__name__ = cmd.__name__
        self._args = args
        self._kwargs = kwargs
        self._join = join
        self._counter = 0

    def __call__(self, sequence, *args, **kwargs):
        self._counter += 1
        time.sleep(self.preexec(sequence))
        LOGGER.info('RUN %s.', self._cmd.__name__)
        rtn = self._cmd(*args, **kwargs)
        LOGGER.info('DONE %s.', self._cmd.__name__)
        time.sleep(self.postexec(sequence))
        return rtn

    @property
    def join(self):
        return self._join

    @property
    def args(self):
        return self._args

    @property
    def kwargs(self):
        return self._kwargs

    @property
    def counter(self):
        """Times a :obj:`BaseCmd` was called."""
        return self._counter

    def check(self, sequence):
        """
        Used by :obj:`Sequence` to check each pass if :obj:`BaseCmd` should
        be called.

        :obj:`Sequence` will pass itself to :meth:`check`, :meth:`preexec` and
        :meth:`postexec` to provide those methods access to the applied
        :attr:`Sequence.timer` and :attr:`Sequence.cmds`.

        :args Sequence sequence:    :obj:`Sequence`-object.
        :rtype:                     bool.
        """
        return True

    def preexec(self, sequence):
        """
        Called by :obj:`Sequence` each pass *before* processing :obj:`BaseCmd`.
        The return-value will be passed to :meth:`time.sleep` to possibly stall
        the execution of :obj:`BaseCmd`.

        :args Sequence sequence:    :obj:`Sequence`-object.
        :returns:                   int or float. ``0`` if execution should not
                                    been stalled.
        """
        return 0

    def postexec(self, sequence):
        """
        Called by :obj:`Sequence` each pass *after* processing :obj:`BaseCmd`.
        The return-value will be passed to :meth:`time.sleep` to possibly stall
        the execution of following :obj:`BaseCmd`.

        :args Sequence sequence:    :obj:`Sequence`-object.
        :returns:                   int or float. ``0`` if execution should not
                                    been stalled.
        """
        return 0



class Cmd(BaseCmd):
    """
    More advanced class for callables for a sequence.
    """
    #TODO: maxcount after that the cmd will be removed from the list
    #TODO: nthday-, nthhour-, nthminute-parameter
    def __init__(self, cmd, join=False, args=list(), kwargs=dict(), wait=0,
                    stall = 0, delay = 0, nthtime = 1, times=list()):
        """
        Constructor of Command.

        :arg callable cmd:          The callable to run within a sequence.
        :keyword list args:         Arguments to pass to *cmd*.
        :keyword dict kwargs:       Keywords to pass to *cmd*.
        :keyword bool join:         If *cmd* should be called as joined
                                    :obj:`threading.Thread`.
        :keyword int wait:          Stall execution of :obj:`Cmd`.
        :keyword int stall:         Stall execution of the following :obj:`Cmd`
        :keyword int delay:         Earliest time within a pass :obj:`Cmd` should
                                    be executed.
        :keyword int nthtime:       :obj:`Cmd` will be executed each nth pass
        :keyword list times:        :obj:`datetime.time`-objects. :obj:`Cmd` will
                                    be only executed on the chance that follows
                                    immediately after :obj:`datetime.time`.
        """
        super(Cmd, self).__init__(cmd, args, kwargs, join)
        self._wait = wait
        self._stall = stall
        self._delay = delay
        self._nthtime = nthtime
        self._times = times

    def check(self, sequence):
        return  self._check_times(sequence.timer.interval) and \
                self._check_nthtime(sequence.timer.counter)

    def preexec(self, sequence):
        return self._wait + self._check_delay(sequence.timer.runtime)

    def postexec(self, sequence):
        return self._stall

    def _check_times(self, interval):
        """
        Checks for execution with regard to *times*.

        :arg int interval:      :attr:`Sequence.timer.interval`
        :returns:               bool
        """
        if not self._times: return True
        d = DayTime.daytime()
        i = interval
        if any([d >= t and d - t < i for t in self._times]): return True
        else: return False

    def _check_nthtime(self, counter):
        """
        Checks for execution with regard to *nthtime*.

        :arg int counter:      :attr:`Sequence.timer.counter`
        :returns:               bool
        """
        return bool(counter % self._nthtime == 0)

    def _check_delay(self, runtime):
        """
        Checks the time till execution with regard to *delay*.

        :arg float runtime:     :attr:`Sequence.timer.runtime`
        :returns:               time till execution
        :rtype:                 bool
        """
        delay = self._delay - runtime
        return delay if delay > 0 else 0


