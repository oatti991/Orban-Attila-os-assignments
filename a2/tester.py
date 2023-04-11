#!/usr/bin/env python3
import re, os, sys, socket, struct, subprocess, json, base64
import threading, ctypes, ctypes.util, tarfile, io, posixpath
import argparse

A2_PROG = "a2"
SEM_NAME = "A2_HELPER_SEM_17871"
SERVER_PORT = 1988

VERBOSE = False
TIME_LIMIT = 3

COMPILE_LOG_FILE_NAME = "compile_log.txt"

try:
    import docker
    DOCKER_AVAILABLE = True
except ModuleNotFoundError:
    DOCKER_AVAILABLE = False

def compile():
    if os.path.isfile(A2_PROG):
        os.remove(A2_PROG)
    LOG_FILE = "compile_log.txt"
    compLog = open(LOG_FILE, "w")
    subprocess.call(["gcc", "-Wall", "%s.c" % A2_PROG, "%s_helper.c" % A2_PROG, "-o", A2_PROG, "-pthread", "-lrt"], 
                        stdout=compLog, stderr=compLog)
    compLog.close()
    if os.path.isfile(A2_PROG):
        compLog = open(LOG_FILE)
        logContent = compLog.read()
        compLog.close()
        if "warning" in logContent:
            return 1
        return 2
    else:
        return 0

class Info:
    BEGIN = 1
    END = 2

    def __init__(self, msg):
        self.proc = msg[1]
        self.th = msg[2]
        self.pid = msg[3]
        self.ppid = msg[4]
        self.tid = msg[5]
        self.timeStart = 0
        self.timeEnd = 0

    def __repr__(self):
        return "P%d T%d pid=%d ppid=%d tid=%d [%d - %d]" % (self.proc, self.th, 
                    self.pid, self.ppid, self.tid, self.timeStart, self.timeEnd)


class Server(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.reset()
        self.shouldStop = False
        self.servSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.servSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.servSocket.bind(("localhost", SERVER_PORT))
        self.servSocket.listen(5)

    def reset(self):
        self.time = 0
        self.infos = {}
        self.errors = []
        self.delays = {}

    def addInfo(self, msg):
        i = Info(msg)
        key = (i.proc, i.th)
        if msg[0] != Info.BEGIN and msg[0] != Info.END:
            self.errors.append("unknonwn message type %d for process %d, thread %d" % (msg[0], i.proc, i.th))
            return -1
        key = (i.proc, i.th)
        if key in self.infos:
            if msg[0] == Info.BEGIN:
                self.errors.append("more than one BEGIN for process %d, thread %d" % (i.proc, i.th))
                return -1
            else:
                if self.infos[key].timeEnd != 0:
                    self.errors.append("more than one END for process %d, thread %d" % (i.proc, i.th))
                    return -1
                else:
                    self.time += 1
                    self.infos[key].timeEnd = self.time
        else:
            if msg[0] == Info.END:
                self.errors.append("END before BEGIN for process %d, thread %d" % (i.proc, i.th))
                return -1
            else:
                self.time += 1
                i.timeStart = self.time
                self.infos[key] = i
        if msg[0] == Info.BEGIN and key in self.delays:
            return self.delays[key]
        return 0


    def run(self):
        while True:
            (clientSocket, _address) = self.servSocket.accept()
            if self.shouldStop:
                self.servSocket.close()
                break
            msg_size_remaining = 6 * 4
            msg = bytes()
            while msg_size_remaining != 0:
                current_buffer = clientSocket.recv(msg_size_remaining)
                if len(current_buffer) == 0:
                    break
                msg += current_buffer
                msg_size_remaining -= len(current_buffer)
            if len(msg) == 6 * 4:
                msg = struct.unpack("i"*6, msg)
                delay = self.addInfo(msg)
            else:
                delay = -10
            if delay < 0:
                # there was an error, we will stop the test
                clientSocket.sendall(struct.pack("i", 0))
            else:
                clientSocket.sendall(struct.pack("i", delay))

    def stop(self):
        self.shouldStop = True
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("localhost", SERVER_PORT))

def checkProcessHierarchy(data, infos):
    errors = []
    score = 0
    n = int(data["nrProcs"])
    procInfos = {}
    for (p, t), info in infos.items():
        if t == 0:
            if p >= 1 and p <= n:
                if info.timeEnd == 0:
                    errors.append("missing END for main thread of process %d" % p)
                    return errors, score
                else:
                    procInfos[p] = info
            else:
                errors.append("found unrequired process %d" % p)
                return errors, score
    if len(procInfos) < n:
        missing = []
        for p in range(1, n+1):
            if p not in procInfos:
                missing.append(str(p))
        errors.append("missing main thread for processes: " + (" ".join(missing)))
        return errors, score
    score += 2
    for p, info in procInfos.items():
        if p != 1:
            parent = int(data["procs"][str(p)])
            parentInfo = procInfos[parent]
            if info.ppid != parentInfo.pid:
                errors.append("the parent for process %d is not %d" % (p, parent))
            if info.timeStart < parentInfo.timeStart:
                errors.append("process %d starts before its parent %d" % (p, parent))
            if info.timeEnd > parentInfo.timeEnd:
                errors.append("process %d ends after its parent %d" % (p, parent))
    if len(errors) > 0:
        return errors, score
    score += 3
    return errors, score

def checkThreads1(data, infos):
    score = 0
    errors = []
    procNr = int(data["threads1_proc"])
    thCount = int(data["threads1_count"])
    thOuter = int(data["threads1_outer"])
    thInner = int(data["threads1_inner"])

    if (procNr, 0) in infos:
        mainTid = infos[(procNr, 0)].tid
    else:
        errors.append("main thread is missing for process %d" % procNr)
        return errors, score
    thInfos = {}
    for (p, t), info in infos.items():
        if p == procNr and t != 0:
            if t >= 1 and t <= thCount:
                if info.timeEnd == 0:
                    errors.append("missing END for thread %d in process %d" % (t, procNr))
                    return errors, score
                elif info.tid == mainTid:
                    errors.append("thread T%d.%d is the same as the main thread of the process" % (procNr, t))
                    return errors, score
                else:
                    thInfos[t] = info
            else:
                errors.append("found unrequired thread %d in process %d" % (t, procNr))
                return errors, score
    if len(thInfos) > 0:
        score += 1
    if len(thInfos) < thCount:
        missing = []
        for t in range(1, thCount+1):
            if t not in thInfos:
                missing.append(str(t))
        errors.append("missing threads %s in process %d" % (" ".join(missing), procNr))
        return errors, score
    score += 1
    if thInfos[thOuter].timeStart < thInfos[thInner].timeStart:
        score += 1
    else:
        errors.append("thread T%d.%d starts after T%d.%d" % (procNr, thOuter, procNr, thInner))
    if thInfos[thOuter].timeEnd > thInfos[thInner].timeEnd:
        score += 1
    else:
        errors.append("thread T%d.%d ends before T%d.%d" % (procNr, thOuter, procNr, thInner))
    if score == 4:
        score = 5
    return errors, score

def checkThreads2(data, infos):
    score = 0
    errors = []
    procNr = int(data["threads2_proc"])
    thCount = int(data["threads2_count"])
    thWaiter = int(data["threads2_waiter"])
    maxThreads = int(data["threads2_max"])

    if (procNr, 0) in infos:
        mainTid = infos[(procNr, 0)].tid
    else:
        errors.append("main thread is missing for process %d" % procNr)
        return errors, score
    thInfos = {}
    for (p, t), info in infos.items():
        if p == procNr and t != 0:
            if t >= 1 and t <= thCount:
                if info.timeEnd == 0:
                    errors.append("missing END for thread %d in process %d" % (t, procNr))
                    return errors, score
                elif info.tid == mainTid:
                    errors.append("thread T%d.%d is the same as the main thread of the process" % (procNr, t))
                    return errors, score
                else:
                    thInfos[t] = info
            else:
                errors.append("found unrequired thread %d in process %d" % (t, procNr))
                return errors, score
    if len(thInfos) < thCount:
        missing = []
        for t in range(1, thCount+1):
            if t not in thInfos:
                missing.append(str(t))
        errors.append("missing thread(s) %s in process %d" % (" ".join(missing), procNr))
        return errors, score
    score += 1

    times = {}
    for info in thInfos.values():
        for t in range(info.timeStart, info.timeEnd+1):
            if t not in times:
                times[t] = []
            times[t].append(info.th)
    violation = False
    for t in sorted(times.keys()):
        if len(times[t]) > maxThreads:
            errors.append("the following threads are running at the same time: %s" % 
                                " ".join([str(th) for th in times[t]]))
            violation = True
            break
    if not violation:
        score += 1
    waiterGroup = times[thInfos[thWaiter].timeEnd]
    if len(waiterGroup) != maxThreads:
        errors.append("the following threads are running while ending thread T%d.%d: %s" % 
                                (procNr, thWaiter, " ".join([str(th) for th in waiterGroup])))
    else:
        score += 1

    if score == 3:
        score = 5
    return errors, score

def checkThreads3(data, infos):
    score = 0
    errors = []
    procNr = int(data["threads3_proc"])
    thCount = int(data["threads3_count"])
    thBefore = int(data["threads3_before"])
    thAfter = int(data["threads3_after"])
    proc1 = int(data["threads1_proc"])
    proc1Th = int(data["threads1_3"])

    if (procNr, 0) in infos:
        mainTid = infos[(procNr, 0)].tid
    else:
        errors.append("main thread is missing for process %d" % procNr)
        return errors, score
    thInfos = {}
    for (p, t), info in infos.items():
        if p == procNr and t != 0:
            if t >= 1 and t <= thCount:
                if info.timeEnd == 0:
                    errors.append("missing END for thread %d in process %d" % (t, procNr))
                    return errors, score
                elif info.tid == mainTid:
                    errors.append("thread T%d.%d is the same as the main thread of the process" % (procNr, t))
                    return errors, score
                else:
                    thInfos[t] = info
            else:
                errors.append("found unrequired thread %d in process %d" % (t, procNr))
                return errors, score
    if len(thInfos) < thCount:
        missing = []
        for t in range(1, thCount+1):
            if t not in thInfos:
                missing.append(str(t))
        errors.append("missing threads %s in process %d" % (" ".join(missing), procNr))
        return errors, score
    score += 1
    if (proc1, proc1Th) not in infos:
        errors.append("thread %d is missing from process %d" % (proc1Th, proc1))
        return errors, score
    info1 = infos[(proc1, proc1Th)]
    if info1.timeStart > thInfos[thBefore].timeEnd:
        score += 1
    else:
        errors.append("thread T%d.%d starts before T%d.%d ended" % (proc1, proc1Th, procNr, thBefore))
    if info1.timeEnd < thInfos[thAfter].timeStart:
        score += 1
    else:
        errors.append("thread T%d.%d ends after T%d.%d started" % (proc1, proc1Th, procNr, thAfter))
    if score == 3:
        score = 5
    
    return errors, score

class Tester(threading.Thread):
    CHECK_FUNCTIONS = [
                        (checkProcessHierarchy, "process hierarchy"),
                        (checkThreads1, "threads from the same process"),
                        (checkThreads2, "threads barrier"),
                        (checkThreads3, "threads from different processes")
                    ]
    CHECK_MAX_SCORE = 5

    def __init__(self, nr, server, data):
        threading.Thread.__init__(self)
        print("\033[1;35mTest %d...\033[0m" % nr)
        self.server = server
        self.cmd = ["./%s" % A2_PROG]
        self.timeLimit = TIME_LIMIT
        self.result = None
        self.p = None
        self.data = data
        self.delays = {}

        # add delays for leaf processes
        if nr in (2, 3, 4):
            for p in self.data["procs"]:
                if p not in self.data["procs"].values():
                    self.delays[(int(p), 0)] = nr * 40000
        # add delays for "Synchronizing threads from the same process"
        if nr in (2, 4):
            p1 = int(self.data["threads1_proc"])
            #to = int(self.data["threads1_outer"])
            ti = int(self.data["threads1_inner"])
            self.delays[(p1, ti)] = 100000 * nr
        # add delays for "Synchronizing threads from different processes"
        if nr in (3, 4):
            p1 = int(self.data["threads1_proc"])
            p3 = int(self.data["threads3_proc"])
            tw = int(self.data["threads1_3"])
            tb = int(self.data["threads3_before"])
            #ta = int(self.data["threads3_after"])
            self.delays[(p3, tb)] = 50000 * nr
            self.delays[(p1, tw)] = 70000 * nr
        # add delays for "Threads barrier"
        if nr in (2, 3):
            p2 = int(self.data["threads2_proc"])
            p2_count = int(self.data["threads2_count"])
            tw = int(self.data["threads2_waiter"])
            if nr == 2:
                self.delays[(p2, tw)] = 250000
            elif nr == 3:
                for t in range(1, p2_count+1):
                    if t != tw:
                        self.delays[(p2, t)] = 10000
        # add delays to enforce concurrency in "Threads barrier"
        if nr == 5:
            p2 = int(self.data["threads2_proc"])
            p2_count = int(self.data["threads2_count"])
            d = 2 * TIME_LIMIT * 1000000 // p2_count
            for t in range(1, p2_count+1):
                self.delays[(p2, t)] = d

    def run(self):
        self.server.reset()
        self.server.delays = self.delays
        if VERBOSE:
            self.p = subprocess.Popen(self.cmd)
        else:
            self.p = subprocess.Popen(self.cmd, stdout=open(os.devnull, "w"), stderr=open(os.devnull, "w"))
        self.p.wait()

    def perform(self):
        timeout = False
        self.start()
        self.join(self.timeLimit)

        if self.is_alive():
            if self.p is not None:
                self.p.kill()
                timeout = True
            self.join()

        if timeout:
            print("\t\033[1;31mTIME LIMIT EXCEEDED\033[0m")
            return 0, Tester.CHECK_MAX_SCORE * len(Tester.CHECK_FUNCTIONS)

        score = 0
        for err in self.server.errors:
            print("\t%s" % err)
        if len(self.server.errors) == 0:
            for checkFn, checkName in Tester.CHECK_FUNCTIONS:
                print("\tChecking %s..." % checkName)
                errors, testScore = checkFn(self.data, self.server.infos)
                for err in errors:
                    print("\t\t%s" % err)
                if testScore == Tester.CHECK_MAX_SCORE:
                    print("\t\t\033[1;32mCORRECT        \033[0m", end="")
                elif testScore > 0:
                    print("\t\t\033[1;33mPARTIAL CORRECT\033[0m", end="")
                else:
                    print("\t\t\033[1;31mFAIL           \033[0m", end="")
                print(" [%d point(s)]" % testScore)
                score += testScore

        return score, Tester.CHECK_MAX_SCORE * len(Tester.CHECK_FUNCTIONS)

def resetSemaphore():
    O_CREAT = 0x0200
    _lib = ctypes.CDLL(ctypes.util.find_library("pthread"))
    _sem_unlink = _lib.sem_unlink
    _sem_unlink.argtypes = (ctypes.c_char_p, )
    _sem_unlink(SEM_NAME.encode())

class DockerHelper:
    _REPO_NAME = "coprisa/utcn-os"
    _TAG_NAME = "os-hw"
    _WORKING_DIR = "/hw"

    def __init__(self):
        self.client = docker.from_env()
        self.container = None
        print("pulling docker image")
        self.client.images.pull(DockerHelper._REPO_NAME, tag=DockerHelper._TAG_NAME)
        print("docker image pulled")

    def runContainer(self):
        self.container = self.client.containers.run("%s:%s" % (DockerHelper._REPO_NAME, DockerHelper._TAG_NAME), detach=True)

    def removeContainer(self):
        self.container.remove(force=True)
        self.container = None

    def copyDir(self, dirPath):
        RX_USEFUL_FILE = re.compile(r".*(?:\.py)|(?:\.c)|(?:\.h)|(?:_data\.json)$")
        tarStream = io.BytesIO()
        tar = tarfile.TarFile(fileobj=tarStream, mode="w")
        for fname in os.listdir(dirPath):
            fpath = os.path.join(dirPath, fname)
            if os.path.isfile(fpath) and RX_USEFUL_FILE.search(fname):
                tar.add(fpath, arcname=fname)
        tar.close()
        tarStream.seek(0)
        self.container.put_archive(DockerHelper._WORKING_DIR, tarStream)

    def execute(self, command):
        res = self.container.exec_run(command)
        return res.output.decode("utf-8", "ignore")

    def copyCompileLogFileInCurrentDirectory(self):
        stream, _stat = self.container.get_archive(posixpath.join(DockerHelper._WORKING_DIR, COMPILE_LOG_FILE_NAME))
        file_obj = io.BytesIO()
        for c in stream:
            file_obj.write(c)
        file_obj.seek(0)
        tar = tarfile.open(mode="r", fileobj=file_obj)
        tar.extractall(".")

    def getContainerId(self):
        if self.container is not None:
            return self.container.short_id
        else:
            return None

def main():
    parser = argparse.ArgumentParser(prog="tester.py")
    parser.add_argument("-d", "--docker", 
        action = "store_true",
        help = "Runs the tests inside a docker container.")
    parser.add_argument("-p", "--docker-persist", 
        action = "store_true",
        help = "Runs the tests inside a docker container and keep the container afterwards.")
    parser.add_argument("-v", "--verbose", 
        action = "store_true",
        help = "Displays more details.")
    args = parser.parse_args()

    if args.docker or args.docker_persist:
        if not DOCKER_AVAILABLE:
            print("\033[1;31mPlease install the docker module for Python")
            sys.exit()
        containerArgs = []
        if args.verbose:
            containerArgs.append("-v")
        dh = DockerHelper()
        dh.runContainer()
        dh.copyDir(".")
        logFile = open("tester_docker.log", "w")
        res = dh.execute(["python3", "tester.py"] + containerArgs)
        logFile.write(res)
        logFile.close()
        dh.copyCompileLogFileInCurrentDirectory()
        print(res)
        if args.docker_persist:
            containerId = dh.getContainerId()
            print(f"\nThe tests were run in the container {containerId}. To attach to it, run:\n    docker exec -it {containerId} /bin/sh")
            print(f"Don't forget to remove it after you finish using it, by running:\n    docker rm -f {containerId}")
        else:
            try:
                dh.removeContainer()
            except docker.errors.APIError:
                print("Could not remove docker container.")
    else:
        if args.verbose:
            global VERBOSE
            VERBOSE = True
        compileRes = compile()
        if compileRes == 0:
            print("COMPILATION ERROR")
        else:
            score = 0
            resetSemaphore()
            serv = Server()
            serv.start()

            with open("a2_data.json") as a2_data:
                content = a2_data.read()
                decoded_data = base64.b64decode(content).decode("utf-8")
                data = json.loads(decoded_data)

            score = 0
            maxScore = 0
            for t in range(1,6):
                tester = Tester(t, serv, data)
                testScore, testMaxScore = tester.perform()
                score += testScore
                maxScore += testMaxScore
            serv.stop()
            print("Total score: %d / %d" % (score, maxScore))
            score = 100.0 * score / maxScore
            if compileRes == 1:
                print("\033[1;31mThere were some compilation warnings. A 10% penalty will be applied.\033[0m")
                score = score * 0.9
            print("Assignment grade: %.2f / 100" % score)


if __name__ == "__main__":
    main()
