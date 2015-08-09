from twisted.trial._dist.disttrial import DistTrialRunner
from twisted.python.filepath import FilePath
from twisted.internet.defer import DeferredList
from twisted.internet.task import cooperate

from twisted.trial.util import _unusedTestDirectory
from twisted.trial._asyncrunner import _iterateTests
from twisted.trial._dist.worker import LocalWorkerAMP


class Runner(DistTrialRunner):

    def prepareRun(self, reactor=None):
        """
        Spawn local worker processes for running load tests.
        """
        if reactor is None:
            from twisted.internet import reactor
        self.reactor = reactor
        testDir, testDirLock = _unusedTestDirectory(
            FilePath(self._workingDirectory))
        workerNumber = self._workerNumber
        ampWorkers = [LocalWorkerAMP() for x in xrange(workerNumber)]
        workers = self.createLocalWorkers(ampWorkers, testDir.path)
        processEndDeferreds = [worker.endDeferred for worker in workers]
        self.launchWorkerProcesses(reactor.spawnProcess, workers,
                                   self._workerArguments)
        self.processEndDeferreds = processEndDeferreds
        self.ampWorkers = ampWorkers
        self.testDirLock = testDirLock

    def run(self, suite):
        """
        Spawn local worker processes and load tests. After that, run them.

        @param suite: A tests suite to be run.

        @param reactor: The reactor to use, to be customized in tests.
        @type reactor: A provider of
            L{twisted.internet.interfaces.IReactorProcess}

        @param cooperate: The cooperate function to use, to be customized in
            tests.
        @type cooperate: C{function}

        @param untilFailure: If C{True}, continue to run the tests until they
            fail.
        @type untilFailure: C{bool}.

        @return: The test result.
        @rtype: L{DistReporter}
        """
        processEndDeferreds = self.processEndDeferreds
        ampWorkers = self.ampWorkers
        testDirLock = self.testDirLock
        count = suite.countTestCases()
        self._stream.write("Running %d tests.\n" % (count,))
        result = self._makeResult()
        if not count:
            # Take a shortcut if there is no test
            suite.run(result.original)
            self.writeResults(result)
            return result

        def runTests():
            testCases = iter(list(_iterateTests(suite)))

            workerDeferreds = []
            for worker in ampWorkers:
                workerDeferreds.append(
                    self._driveWorker(worker, result, testCases,
                                      cooperate=cooperate))
            return DeferredList(workerDeferreds, consumeErrors=True,
                                fireOnOneErrback=True)

        stopping = []

        def nextRun(ign):
            self.writeResults(result)

        def stop(ign):
            testDirLock.unlock()
            if not stopping:
                stopping.append(None)
                self.reactor.stop()

        def beforeShutDown():
            if not stopping:
                stopping.append(None)
                d = DeferredList(processEndDeferreds, consumeErrors=True)
                return d.addCallback(continueShutdown)

        def continueShutdown(ign):
            self.writeResults(result)
            return ign

        d = runTests()
        d.addCallback(nextRun)
        d.addBoth(stop)

        self.reactor.addSystemEventTrigger('before', 'shutdown', beforeShutDown)
        self.reactor.run()

        return result
