#!/usr/bin/env python3
import re, os, sys, struct, subprocess, json, base64
import threading, ctypes, ctypes.util, random, tarfile, io, posixpath
import argparse

A3_PROG = "a3"

VERBOSE = False
TIME_LIMIT = 3

COMPILE_LOG_FILE_NAME = "compile_log.txt"

try:
    import docker
    DOCKER_AVAILABLE = True
except ModuleNotFoundError:
    DOCKER_AVAILABLE = False

def compile():
    if os.path.isfile(A3_PROG):
        os.remove(A3_PROG)
    LOG_FILE = "compile_log.txt"
    compLog = open(LOG_FILE, "w")
    subprocess.call(["gcc", "-Wall", "%s.c" % A3_PROG, "-o", A3_PROG, "-lrt"], 
                        stdout=compLog, stderr=compLog)
    compLog.close()
    if os.path.isfile(A3_PROG):
        compLog = open(LOG_FILE)
        logContent = compLog.read()
        compLog.close()
        if "warning" in logContent:
            return 1
        return 2
    else:
        return 0

class Tester(threading.Thread):
    MAX_SCORE = 10

    PROT_READ = 1
    PROT_WRITE = 2
    MAP_SHARED = 1
    O_RDONLY = 0

    def __init__(self, data, name, params, checkMap):
        threading.Thread.__init__(self, daemon=True)
        print("\033[1;35mTesting %s...\033[0m" % name)
        self._initIpc()
        self.cmd = ["strace", "-o", "strace.log", "-e", "trace=open,openat,mmap,read", "./%s" % A3_PROG]
        self.name = name
        self.params = params
        self.checkMap = checkMap
        self.timeLimit = TIME_LIMIT
        self.result = None
        self.p = None
        self.data = data
        self.score = 0
        self.fdCmd = None
        self.fdRes = None
        self.maxScore = Tester.MAX_SCORE

    def _initIpc(self):
        self.libc = ctypes.CDLL("libc.so.6")
        try:
            self.librt = ctypes.CDLL("librt.so")
        except OSError:
            self.librt = ctypes.CDLL("librt.so.1")

        self.shm_open = self.librt.shm_open
        self.shm_open.argtypes = (ctypes.c_char_p, ctypes.c_int, ctypes.c_int)
        self.shm_open.restype = ctypes.c_int

        self.shm_unlink = self.librt.shm_unlink
        self.shm_unlink.argtypes = (ctypes.c_char_p, )
        self.shm_unlink.restype = ctypes.c_int

        self.mmap = self.libc.mmap
        self.mmap.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_size_t)
        self.mmap.restype = ctypes.c_void_p

        self.munmap = self.libc.munmap
        self.munmap.argtypes = (ctypes.c_void_p, ctypes.c_size_t)
        self.munmap.restype = ctypes.c_int

    def _removeShm(self):
        self.shm_unlink(self.data["shm_name"].encode())

    def checkStrace(self):
        rx = re.compile(rb"([a-z]+)\((.*)\)\s+=\s+([a-z0-9]+)")
        fin = open("strace.log", "rb")
        content = fin.read()
        fin.close()
        matches = rx.findall(content)
        fds = {}
        mappedFds = set()
        readFds = set()
        for (call, params, result) in matches:
            params = params.split(b",")
            if call == b"open":
                fds[result] = params[0].strip()
            elif call == b"openat":
                fds[result] = params[1].strip()
            elif call == b"read":
                readFds.add(params[0].strip())
            elif call == b"mmap":
                mappedFds.add(params[4].strip())
        for fd in readFds:
            if (fd in fds) and (b"test_root" in fds[fd]):
                print("[TESTER] read system call detected on file %s" % fds[fd])
                return False
        for fd, fname in fds.items():
            if (b"test_root" in fname) and (fd not in mappedFds):
                print("[TESTER] no mmap system call on file %s" % fds[fd])
                return False
        return True

        
    def readNumber(self):
        if self.fdRes is None:
            return None
        try:
            x = self.fdRes.read(4)
            if len(x) != 4:
                return None
            x = struct.unpack("I", x)[0]
            print("[TESTER] received number %u" % x)
            return x
        except IOError:
            self.fdRes = None
            return None

    def readString(self):
        if self.fdRes is None:
            return None
        try:
            if self.data["strings_size_first"]:
                size = self.fdRes.read(1)
                if len(size) != 1:
                    return None
                size = struct.unpack("B", size)[0]
                s = self.fdRes.read(size)
                if len(s) != size:
                    return None
                s = s.decode()
            else:
                s = []
                while True:
                    c = self.fdRes.read(1).decode()
                    if len(c) != 1 or len(s) > 255:
                        return None
                    if c == self.data["strings_terminator"]:
                        break
                    else:
                        s.append(c)
                s = "".join(s)
            print("[TESTER] received string '%s'" % s)
            return s
        except IOError:
            self.fdRes = None
            return None

    def writeNumber(self, nr):
        if self.fdCmd is None:
            return None
        try:
            print("[TESTER] sending number %u" % nr)
            self.fdCmd.write(struct.pack("I", nr))
            self.fdCmd.flush()
        except IOError:
            self.fdCmd = None

    def writeString(self, s):
        if self.fdCmd is None:
            return None
        if isinstance(s, bytes):
            s = s.decode()
        print("[TESTER] sending string '%s'" % s)
        try:
            if self.data["strings_size_first"]:
                self.fdCmd.write(struct.pack("B", len(s)))
                self.fdCmd.flush()
            self.fdCmd.write(s.encode())
            self.fdCmd.flush()
            if not self.data["strings_size_first"]:
                self.fdCmd.write(self.data["strings_terminator"].encode())
                self.fdCmd.flush()
        except IOError:
            self.fdCmd = None

    def test_ping(self, _params):
        self.writeString(self.data["ping_command"][0])
        r = self.readString()
        if r != self.data["ping_command"][0]:
            return 0
        if self.data["ping_variant_first"]:
            var = self.readNumber()
            resp = self.readString()
        else:
            resp = self.readString()
            var = self.readNumber()
        if resp != self.data["ping_command"][1] or var != int(self.data["variant"]):
            return 0
        return self.maxScore

    def test_shm1(self, _params):
        self._removeShm()
        self.writeString("CREATE_SHM")
        self.writeNumber(int(self.data["shm_size"]))
        r = self.readString()
        if r != "CREATE_SHM":
            return 0
        r = self.readString()
        if r != "SUCCESS":
            return 0
        # check if the shm actually exists
        #shm = self.shmget(int(self.data["shm_key"]), int(self.data["shm_size"]), 0)
        shm = self.shm_open(self.data["shm_name"].encode(), Tester.O_RDONLY, 0)
        if shm < 0:
            print("[TESTER] shm with name %s not found" % self.data["shm_name"])
            return 0
        return self.maxScore

    def test_shm_write(self, _params):
        score = 0
        self._removeShm()
        self.writeString("CREATE_SHM")
        self.writeNumber(int(self.data["shm_size"]))
        r = self.readString()
        if r != "CREATE_SHM":
            return score
        r = self.readString()
        if r != "SUCCESS":
            return score
        # check if the shm actually exists
        shm = self.shm_open(self.data["shm_name"].encode(), Tester.O_RDONLY, 0)
        if shm < 0:
            print("[TESTER] shm with name %s not found" % self.data["shm_name"])
            return score
        score = 3
        shmAddr = self.mmap(None, int(self.data["shm_size"]), Tester.PROT_READ, Tester.MAP_SHARED, shm, 0)
        self.writeString("WRITE_TO_SHM")
        self.writeNumber(int(self.data["shm_write_offset"]))
        self.writeNumber(int(self.data["shm_write_value"]))
        r = self.readString()
        if r != "WRITE_TO_SHM":
            return score
        r = self.readString()
        if r != "SUCCESS":
            return score
        val = ctypes.string_at(shmAddr + int(self.data["shm_write_offset"]), 4)
        val = struct.unpack("I", val)[0]
        if val != int(self.data["shm_write_value"]):
            print("[TESTER] found %d value; expected: %s" % (val, self.data["shm_write_value"]))
        else:
            score += 5

        self.writeString("WRITE_TO_SHM")
        self.writeNumber(int(self.data["shm_size"])-2)
        self.writeNumber(0x12345678)
        r = self.readString()
        if r != "WRITE_TO_SHM":
            return score
        r = self.readString()
        if r != "ERROR":
            return score
        score += 2

        return score

    def test_map_inexistent(self, fname):
        self.maxScore = 5
        score = 0
        self.writeString("MAP_FILE")
        self.writeString(fname)
        r = self.readString()
        if r != "MAP_FILE":
            return score
        r = self.readString()
        if r != "ERROR":
            return score
        return self.maxScore

    def test_map1(self, fname):
        self.maxScore = 5
        score = 0
        self.writeString("MAP_FILE")
        self.writeString(fname)
        r = self.readString()
        if r != "MAP_FILE":
            return score
        r = self.readString()
        if r != "SUCCESS":
            return score
        return self.maxScore

    def test_read_offset(self, fname):
        score = 0
        self._removeShm()
        self.writeString("CREATE_SHM")
        self.writeNumber(int(self.data["shm_size"]))
        r = self.readString()
        if r != "CREATE_SHM":
            return score
        r = self.readString()
        if r != "SUCCESS":
            return score
        # check if the shm actually exists
        shm = self.shm_open(self.data["shm_name"].encode(), Tester.O_RDONLY, 0)
        if shm < 0:
            print("[TESTER] shm with name %s not found" % self.data["shm_name"])
            return score
        shmAddr = self.mmap(None, int(self.data["shm_size"]), Tester.PROT_READ, Tester.MAP_SHARED, shm, 0)
        score = 2

        self.writeString("MAP_FILE")
        self.writeString(fname)
        r = self.readString()
        if r != "MAP_FILE":
            return score
        r = self.readString()
        if r != "SUCCESS":
            return score
        score = 3

        self.writeString("READ_FROM_FILE_OFFSET")
        fsize = os.path.getsize(fname)
        self.writeNumber(fsize + 1)
        self.writeNumber(50)
        r = self.readString()
        if r != "READ_FROM_FILE_OFFSET":
            return score
        r = self.readString()
        if r != "ERROR":
            return score
        score = 5

        self.writeString("READ_FROM_FILE_OFFSET")
        self.writeNumber(fsize//2)
        self.writeNumber(50)
        r = self.readString()
        if r != "READ_FROM_FILE_OFFSET":
            return score
        r = self.readString()
        if r != "SUCCESS":
            return score
        score = 6

        # check the read content
        fin = open(fname, "rb")
        content = fin.read()[fsize//2:fsize//2+50]
        fin.close()
        readContent = ctypes.string_at(shmAddr, 50)
        if readContent != content:
            print("[TESTER] read content incorrect")
        else:
            score = self.maxScore

        return score

    def test_read_section(self, fname):
        score = 0
        self._removeShm()
        self.writeString("CREATE_SHM")
        self.writeNumber(int(self.data["shm_size"]))
        r = self.readString()
        if r != "CREATE_SHM":
            return score
        r = self.readString()
        if r != "SUCCESS":
            return score
        # check if the shm actually exists
        shm = self.shm_open(self.data["shm_name"].encode(), Tester.O_RDONLY, 0)
        if shm < 0:
            print("[TESTER] shm with name %s not found" % self.data["shm_name"])
            return score
        shmAddr = self.mmap(None, int(self.data["shm_size"]), Tester.PROT_READ, Tester.MAP_SHARED, shm, 0)
        score = 1

        self.writeString("MAP_FILE")
        self.writeString(fname)
        r = self.readString()
        if r != "MAP_FILE":
            return score
        r = self.readString()
        if r != "SUCCESS":
            return score
        score = 2

        sections = getSectionsTable(self.data, fname)
        self.writeString("READ_FROM_FILE_SECTION")
        self.writeNumber(len(sections)+2)
        self.writeNumber(0)
        self.writeNumber(100)
        r = self.readString()
        if r != "READ_FROM_FILE_SECTION":
            return score
        r = self.readString()
        if r != "ERROR":
            return score
        score = 4

        fin = open(fname, "rb")
        content = fin.read()
        fin.close()

        sectIds = random.sample(range(len(sections)), 3)
        for sectId in sectIds:
            _name, _type, offset, size = sections[sectId]
            readOffset = random.randint(0, size//2)
            readSize = random.randint(5, size//2)
            expectedContent = content[offset + readOffset : offset + readOffset + readSize]
            self.writeString("READ_FROM_FILE_SECTION")
            self.writeNumber(sectId+1)
            self.writeNumber(readOffset)
            self.writeNumber(readSize)
            r = self.readString()
            if r != "READ_FROM_FILE_SECTION":
                return score
            r = self.readString()
            if r != "SUCCESS":
                return score
            readContent = ctypes.string_at(shmAddr, readSize)
            if readContent != expectedContent:
                print("[TESTER] read content incorrect")
            else:
                score += 2
        return score

    def test_read_logical(self, fname):
        score = 0
        self._removeShm()
        self.writeString("CREATE_SHM")
        self.writeNumber(int(self.data["shm_size"]))
        r = self.readString()
        if r != "CREATE_SHM":
            return score
        r = self.readString()
        if r != "SUCCESS":
            return score
        # check if the shm actually exists
        shm = self.shm_open(self.data["shm_name"].encode(), Tester.O_RDONLY, 0)
        if shm < 0:
            print("[TESTER] shm with name %s not found" % self.data["shm_name"])
            return score
        shmAddr = self.mmap(None, int(self.data["shm_size"]), Tester.PROT_READ, Tester.MAP_SHARED, shm, 0)
        score = 1

        self.writeString("MAP_FILE")
        self.writeString(fname)
        r = self.readString()
        if r != "MAP_FILE":
            return score
        r = self.readString()
        if r != "SUCCESS":
            return score
        score = 2

        fin = open(fname, "rb")
        content = fin.read()
        fin.close()

        rawSections = getSectionsTable(self.data, fname)
        sectIds = random.sample(range(len(rawSections)), 4)
        crtOffset = 0
        toRead = []
        align = int(self.data["logical_space_section_alignment"])
        for sectId, (_name, _type, offset, size) in enumerate(rawSections):
            if sectId in sectIds:
                readOffset = random.randint(0, size//2)
                readSize = random.randint(5, size//2)
                expectedContent = content[offset + readOffset : offset + readOffset + readSize]
                toRead.append((crtOffset + readOffset, readSize, expectedContent))
            crtOffset += ((size + align - 1) // align) * align

        for (logicOffset, size, expectedContent) in toRead:
            self.writeString("READ_FROM_LOGICAL_SPACE_OFFSET")
            self.writeNumber(logicOffset)
            self.writeNumber(size)
            r = self.readString()
            if r != "READ_FROM_LOGICAL_SPACE_OFFSET":
                return score
            r = self.readString()
            if r != "SUCCESS":
                return score
            readContent = ctypes.string_at(shmAddr, size)
            if readContent != expectedContent:
                print("[TESTER] read content incorrect")
            else:
                score += 2
        return score

    def run(self):
        if os.path.exists(self.data["pipeCmd"]):
            os.remove(self.data["pipeCmd"])
        if os.path.exists(self.data["pipeRes"]):
            os.remove(self.data["pipeRes"])
        os.mkfifo(self.data["pipeCmd"], 0o644)

        if VERBOSE:
            self.p = subprocess.Popen(self.cmd)
        else:
            self.p = subprocess.Popen(self.cmd, stdout=open(os.devnull, "w"), stderr=open(os.devnull, "w"))
        # wait for the response pipe creation
        self.fdCmd = open(self.data["pipeCmd"], "wb")
        try:
            self.fdRes = open(self.data["pipeRes"], "rb")
        except FileNotFoundError:
            print("[TESTER] could not open response pipe")

        #wait for the CONNECT message
        s = self.readString()
        if s == self.data["connect_string"]:
            self.score += 1
            sc = getattr(self, "test_" + self.name)(self.params)
            if sc > self.score:
                self.score = sc
            self.writeString("EXIT")
            self.p.wait()
        else:
            self.p.kill()
            self.p = None

        if self.fdRes is not None:
            self.fdRes.close()
        if os.path.exists(self.data["pipeRes"]):
            os.remove(self.data["pipeRes"])
        if self.fdCmd is not None:
            self.fdCmd.close()
        if os.path.exists(self.data["pipeCmd"]):
            os.remove(self.data["pipeCmd"])

    def perform(self):
        timeout = False
        self.start()
        self.join(TIME_LIMIT)

        if self.is_alive():
            if self.p is not None:
                self.p.kill()
                timeout = True
            #self.join()
        if timeout:
            print("\t\033[1;31mTIME LIMIT EXCEEDED\033[0m")
            return 0, self.maxScore
        if self.checkMap:
            if not self.checkStrace():
                self.score *= 0.7
        return self.score, self.maxScore

def genRandomName(length=0):
    symbols = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijlmnopqrstuvwxyz1234567890"
    if length == 0:
        length = random.randint(4, 10)
    name = [symbols[random.randint(0, len(symbols)-1)] for _i in range(length)]
    return "".join(name).encode()

def genSectionFile(path, data):
    info = {}
    
    info["magic"] = data["magic"].encode()
    info["version"] = random.randint(int(data["version_min"]), int(data["version_max"]))
    info["sectNr"] = random.randint(max(4, int(data["nr_sect_min"])), int(data["nr_sect_max"]))
    hdrSize = (int(data["magic_size"]) + 2 + int(data["version_size"]) + 1 +
                            info["sectNr"] * (int(data["section_name_size"]) + 
                                                int(data["section_type_size"]) + 8))

    hdr1 = info["magic"]
    hdr2 = struct.pack("H", hdrSize)

    if not data["header_pos_end"]:
        crtOffset = hdrSize
    else:
        crtOffset = 0
    body = []
    if data["version_size"] == "1":
        hdr3 = [struct.pack("B", info["version"])]
    elif data["version_size"] == "2":
        hdr3 = [struct.pack("H", info["version"])]
    else:
        hdr3 = [struct.pack("I", info["version"])]
    hdr3.append(struct.pack("B", info["sectNr"]))
    for i in range(info["sectNr"]):
        if not data["header_pos_end"]:
            zeros = b"\x00" * random.randint(5, 20)
            body.append(zeros)
            crtOffset += len(zeros)
        sectBody = genRandomName(random.randint(1000, 9000))
        body.append(sectBody)
        sectNameLen = random.randint(int(data["section_name_size"])-2, int(data["section_name_size"]))
        sectName = genRandomName(sectNameLen) + (b"\x00" * (int(data["section_name_size"]) - sectNameLen))
        sectType = int(data["section_types"][random.randint(0, len(data["section_types"])-1)])
        hdr3.append(sectName)
        if data["section_type_size"] == "1":
            hdr3.append(struct.pack("B", sectType))
        elif data["section_type_size"] == "2":
            hdr3.append(struct.pack("H", sectType))
        else:
            hdr3.append(struct.pack("I", sectType))
        hdr3.append(struct.pack("I", crtOffset))
        hdr3.append(struct.pack("I", len(sectBody)))
        crtOffset += len(sectBody)
        if data["header_pos_end"]:
            zeros = b"\x00" * random.randint(5, 20)
            body.append(zeros)
            crtOffset += len(zeros)

    fout = open(path, "wb")
    if not data["header_pos_end"]:
        fout.write(hdr1)
        fout.write(hdr2)
        fout.write(b"".join(hdr3))
        for sectBody in body:
            fout.write(sectBody)
    else:
        for sectBody in body:
            fout.write(sectBody)
        fout.write(b"".join(hdr3))
        fout.write(hdr2)
        fout.write(hdr1)
    fout.close()
    perm = (4+random.randint(0, 3)) * 64 + random.randint(0, 7) * 8 + random.randint(0, 7)
    os.chmod(path, perm)

def getSectionsTable(data, fpath):
    if not os.path.isfile(fpath):
        return None
    fin = open(fpath, "rb")
    content = fin.read()
    fin.close()

    magicSize = int(data["magic_size"])
    if data["header_pos_end"]:
        magic = content[-magicSize:]
    else:
        magic = content[:magicSize]
    if magic != data["magic"].encode():
        return None
    if data["header_pos_end"]:
        hdrSize = struct.unpack("H", content[-magicSize-2:-magicSize])[0]
        hdr = content[-hdrSize:-magicSize-2]
    else:
        hdrSize = struct.unpack("H", content[magicSize:magicSize+2])[0]
        hdr = content[magicSize+2:hdrSize]
    if data["version_size"] == "1":
        version = struct.unpack("B", hdr[0:1])[0]
        nrSect = struct.unpack("B", hdr[1:2])[0]
        hdr = hdr[2:]
    elif data["version_size"] == "2":
        version = struct.unpack("H", hdr[:2])[0]
        nrSect = struct.unpack("B", hdr[2:3])[0]
        hdr = hdr[3:]
    else:
        version = struct.unpack("I", hdr[:4])[0]
        nrSect = struct.unpack("B", hdr[4:5])[0]
        hdr = hdr[5:]
    if version < int(data["version_min"]) or version > int(data["version_max"]):
        return None
    if nrSect < int(data["nr_sect_min"]) or nrSect > int(data["nr_sect_max"]):
        return None
    ns = int(data["section_name_size"])
    ts = int(data["section_type_size"])
    sectSize = ns + ts + 4 + 4
    sections = []
    for i in range(nrSect):
        name = hdr[i*sectSize:i*sectSize+ns]
        name = name.replace(b"\x00", b"")
        type = hdr[i*sectSize+ns:i*sectSize+ns+ts]
        if ts == 1:
            type = struct.unpack("B", type)[0]
        elif ts == 2:
            type = struct.unpack("H", type)[0]
        else:
            type = struct.unpack("I", type)[0]
        if str(type) not in data["section_types"]:
            return None
        offset = struct.unpack("I", hdr[i*sectSize+ns+ts:i*sectSize+ns+ts+4])[0]
        size = struct.unpack("I", hdr[i*sectSize+ns+ts+4:i*sectSize+ns+ts+8])[0]
        sections.append((name, type, offset, size))
    return sections

def loadTests(data):
    random.seed(data["name"])
    tests = [("ping", None, False), 
             ("shm1", None, False), 
             ("shm_write", None, False),
             ("map_inexistent", os.path.join(b"test_root", genRandomName(12) + b"." + genRandomName(3)), False),
            ]
    if not os.path.isdir("test_root"):
        os.mkdir("test_root")
        for _i in range(3):
            genSectionFile(os.path.join(b"test_root", genRandomName(10) + b"." + genRandomName(3)), data)
    fnames = [os.path.join(b"test_root", f) for f in sorted(os.listdir(b"test_root"))]
    tests.append(("map1", fnames[0], True))
    tests.append(("read_offset", fnames[0], True))
    tests.append(("read_section", fnames[1], True))
    tests.append(("read_logical", fnames[2], True))

    return tests

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
            with open("a3_data.json") as a3_data:
                content = a3_data.read()
                decoded_data = base64.b64decode(content).decode('utf-8')
                data = json.loads(decoded_data)

            tests = loadTests(data)

            score = 0
            maxScore = 0
            for name, params, checkMap in tests:
                tester = Tester(data, name, params, checkMap)
                testScore, testMaxScore = tester.perform()
                print("Test score: %d / %d" % (testScore, testMaxScore))
                score += testScore
                maxScore += testMaxScore
            print("\nTotal score: %d / %d" % (score, maxScore))
            score = 100.0 * score / maxScore
            if compileRes == 1:
                print("\033[1;31mThere were some compilation warnings. A 10% penalty will be applied.\033[0m")
                score = score * 0.9
            print("Assignment grade: %.2f / 100" % score)


if __name__ == "__main__":
    main()
