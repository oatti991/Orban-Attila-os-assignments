#!/usr/bin/env python3
import re, os, sys, subprocess, json, base64, io, errno
import posixpath
import threading, random, shutil, struct, time, math, tarfile

A1_PROG = "a1"
VERBOSE = False
VALGRIND = False
TIME_LIMIT = 4

COMPILE_LOG_FILE_NAME = "compile_log.txt"

try:
    import docker
    DOCKER_AVAILABLE = True
except ModuleNotFoundError:
    DOCKER_AVAILABLE = False

class Tester(threading.Thread):
    leaks = False

    def __init__(self, name, command, timeLimit, expectedOutput, unordered):
        threading.Thread.__init__(self)
        print("Testing %s..." % name, end="")
        self.cmd = ["./%s" % A1_PROG] + command
        if VALGRIND:
            self.cmd = ["valgrind"] + self.cmd
        self.timeLimit = timeLimit
        self.expectedOutput = expectedOutput
        self.unordered = unordered
        self.result = None
        self.leak = False
        self.p = None

    def run(self):
        self.p = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, err = self.p.communicate()
        self.result = [line.strip().decode(errors="ignore") for line in output.strip().split(b"\n")]
        if b"LEAK SUMMARY" in err:
            Tester.leaks = True
            self.leak = True

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
            print("\033[1;31mTIME LIMIT EXCEEDED\033[0m")
        if self.unordered:
            verdict = (sorted(self.result) == sorted(self.expectedOutput))
        else:
            verdict = (self.result == self.expectedOutput)
        if verdict:
            print("\033[1;32mOK\033[0m" + (" (with memory leaks)" if self.leak else ""))
            return 1
        else:
            print("\033[1;31mFAIL\033[0m" + (" (with memory leaks)" if self.leak else ""))
            if VERBOSE:
                print("\tExpected output: %s" % str(self.expectedOutput))
                print("\tYour output: %s" % str(self.result))
            return 0

def genRandomName(length=0):
    symbols = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijlmnopqrstuvwxyz1234567890"
    if length == 0:
        length = random.randint(4, 10)
    name = [symbols[random.randint(0, len(symbols)-1)] for _i in range(length)]
    return "".join(name).encode()

def makeRandomDirs(path, count):
    dirs = [path]
    for _i in range(count):
        crtDir = dirs[random.randint(0, len(dirs)-1)]
        newDir = os.path.join(crtDir, genRandomName())
        while newDir in dirs:
            newDir += genRandomName(1)
        dirs.append(newDir)
    for dir in dirs:
        os.mkdir(dir)
    return dirs

def genSectionBody(data, hugeLines):
    if hugeLines:
        nrLines = random.randint(5, 10)
    else:
        nrLines = random.randint(10, 20)
    body = []
    for _i in range(nrLines):
        if hugeLines:
            lineLen = random.randint(90000, 120000)
        else:
            lineLen = random.randint(20, 100)
        body.append(genRandomName(lineLen))
    if data["line_ending_win"]:
        sep = b"\x0D\x0A"
    else:
        sep = b"\x0A"
    return sep.join(body)


def genSectionFile(path, data, wrongMagic=False, wrongVersion=False, wrongSectNr=False, wrongSectTypes=False, hugeLines=False):
    info = {}
    
    info["magic"] = data["magic"].encode()
    if wrongMagic:
        while info["magic"] == data["magic"].encode():
            info["magic"] = genRandomName(int(data["magic_size"]))
    info["version"] = random.randint(int(data["version_min"]), int(data["version_max"]))
    if wrongVersion:
        info["version"] += int(data["version_max"])
        if info["version"] > 255:
            while info["version"] >= int(data["version_min"]):
                info["version"] //= 2
    info["sectNr"] = random.randint(int(data["nr_sect_min"]), int(data["nr_sect_max"]))
    if wrongSectNr:
        info["sectNr"] += int(data["nr_sect_max"])
    
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
            zeros = b"\x00" * random.randint(100, 200)
            body.append(zeros)
            crtOffset += len(zeros)
        sectBody = genSectionBody(data, hugeLines)
        body.append(sectBody)
        sectNameLen = random.randint(int(data["section_name_size"])-2, int(data["section_name_size"]))
        sectName = genRandomName(sectNameLen) + (b"\x00" * (int(data["section_name_size"]) - sectNameLen))
        sectType = int(data["section_types"][random.randint(0, len(data["section_types"])-1)])
        if wrongSectTypes and i == info["sectNr"] // 3:
            sectType = max([int(x) for x in data["section_types"]]) + 2
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
            zeros = b"\x00" * random.randint(100, 200)
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

def get_perm(fpath):
    perm = os.stat(fpath).st_mode & 0o777
    res = []
    for _i in range(3):
        p = perm % 8
        perm //= 8
        if p & 1 != 0:
            res.append("x")
        else:
            res.append("-")
        if p & 2 != 0:
            res.append("w")
        else:
            res.append("-")
        if p & 4 != 0:
            res.append("r")
        else:
            res.append("-")
    return "".join(res[::-1])

def parseFile(data, fpath, section=None, line=None, findall=False, randomLine=False):
    result = []
    if not os.path.isfile(fpath):
        result.append("ERROR")
        result.append("inexistent file")
        return result
    fin = open(fpath, "rb")
    content = fin.read()
    fin.close()

    magicSize = int(data["magic_size"])
    if data["header_pos_end"]:
        magic = content[-magicSize:]
    else:
        magic = content[:magicSize]
    if magic != data["magic"].encode():
        result.append("ERROR")
        result.append("wrong magic")
        return result
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
        result.append("ERROR")
        result.append("wrong version")
        return result
    if nrSect < int(data["nr_sect_min"]) or nrSect > int(data["nr_sect_max"]):
        result.append("ERROR")
        result.append("wrong sect_nr")
        return result
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
            result.append("ERROR")
            result.append("wrong sect_types")
            return result
        offset = struct.unpack("I", hdr[i*sectSize+ns+ts:i*sectSize+ns+ts+4])[0]
        size = struct.unpack("I", hdr[i*sectSize+ns+ts+4:i*sectSize+ns+ts+8])[0]
        sections.append((name, type, offset, size))

    if randomLine:
        sect = random.randint(0, nrSect - 1)
        _name, _type, offset, size = sections[sect]
        if data["line_ending_win"]:
            sep = b"\x0D\x0A"
        else:
            sep = b"\x0A"
        lines = content[offset:offset+size].split(sep)
        lineNr = random.randint(1, len(lines))
        return (sect+1, lineNr)
    if section is None and not findall:
        # parse option was used
        result = ["SUCCESS", "version=%d" % version, "nr_sections=%d" % nrSect]
        for i, (name, type, _offset, size) in enumerate(sections):
            result.append("section%d: %s %d %d" % (i+1, name.decode(), type, size))
    elif section is not None:
        # extract option was used
        if section > len(sections) or section < 1:
            result.append("ERROR")
            result.append("inexistent file")
            return result
        _name, _type, offset, size = sections[section-1]
        if data["line_ending_win"]:
            sep = b"\x0D\x0A"
        else:
            sep = b"\x0A"
        lines = content[offset:offset+size].split(sep)
        if line > len(lines) or line < 1:
            result.append("ERROR")
            result.append("inexistent line")
            return result
        if data["line_count_reversed"]:
            crtLine = lines[-line]
        else:
            crtLine = lines[line-1]
        if data["line_reversed"]:
            crtLine = crtLine[::-1]
        result = ["SUCCESS", crtLine.decode()]
    elif findall:
        # findall option was used
        if data["findall"] == "n_sect_type_t":
            n = int(data["findall_param1"])
            t = int(data["findall_param2"])
            for (_name, type, _offset, _size) in sections:
                if type == t:
                    n -= 1
            if n <= 0:
                return True
        elif data["findall"] == "sect_more_l_lines":
            l = int(data["findall_param1"])
            if data["line_ending_win"]:
                sep = b"\x0D\x0A"
            else:
                sep = b"\x0A"
            for (_name, _type, offset, size) in sections:
                lines = content[offset:offset+size].split(sep)
                if len(lines) > l:
                    return True
        elif data["findall"] == "s_sect_l_lines":
            s = int(data["findall_param1"])
            l = int(data["findall_param2"])
            if data["line_ending_win"]:
                sep = b"\x0D\x0A"
            else:
                sep = b"\x0A"
            for (_name, _type, offset, size) in sections:
                lines = content[offset:offset+size].split(sep)
                if len(lines) == l:
                    s -= 1
            if s<= 0:
                return True
        elif data["findall"] == "no_sect_size_s":
            s = int(data["findall_param1"])
            for (_name, _type, _offset, size) in sections:
                if size > s:
                    return False
            return True
    return result

def perform_a1(data, cmd):
    if len(cmd) == 0:
        return []
    if cmd[0] == "variant":
        return [data["variant"]]
    elif cmd[0] == "list":
        if len(cmd) < 2:
            return []
        mx = re.match(r"^path=(.*)$", cmd[-1])
        if not mx:
            return []
        path = mx.group(1)
        if not os.path.isdir(path):
            return []
        options = {}
        for opt in cmd[1:-1]:
            mx = re.match(r"^([^=]+)=(.*)$", opt)
            if mx:
                optKey = mx.group(1)
                optValue = mx.group(2)
            else:
                optKey = opt
                optValue = None
            options[optKey] = optValue
        results = []
        if "recursive" in options:
            for root, dirs, files in os.walk(path):
                for name in dirs + files:
                    results.append(os.path.join(root, name))
        else:
            results = [os.path.join(path, name) for name in os.listdir(path)]
        results.sort()
        
        if "name_starts_with" in options:
            results = [x for x in results if os.path.basename(x).startswith(options["name_starts_with"])]
        if "name_ends_with" in options:
            results = [x for x in results if os.path.basename(x).endswith(options["name_ends_with"])]
        if "size_greater" in options:
            results = [x for x in results if os.path.isfile(x) and os.path.getsize(x) > int(options["size_greater"])]
        if "size_smaller" in options:
            results = [x for x in results if os.path.isfile(x) and os.path.getsize(x) < int(options["size_smaller"])]
        if "permissions" in options:
            results = [x for x in results if get_perm(x) == options["permissions"]]
        if "has_perm_execute" in options:
            results = [x for x in results if get_perm(x)[2] == "x"]
        if "has_perm_write" in options:
            results = [x for x in results if get_perm(x)[1] == "w"]

        return ["SUCCESS"] + results
    elif cmd[0] == "parse":
        if len(cmd) < 2:
            return []
        mx = re.match(r"^path=(.*)$", cmd[1])
        if not mx:
            return []
        path = mx.group(1)
        return parseFile(data, path)
    elif cmd[0] == "extract":
        if len(cmd) < 4:
            return []
        mx = re.match(r"^path=([^\s]+) section=([0-9]+) line=([0-9]+)$", " ".join(cmd[1:4]))
        if not mx:
            return []
        path = mx.group(1)
        section = int(mx.group(2))
        line = int(mx.group(3))
        return parseFile(data, path, section=section, line=line)
    elif cmd[0] == "findall":
        results = []
        if len(cmd) < 2:
            return []
        mx = re.match(r"^path=(.*)$", cmd[1])
        if not mx:
            return []
        path = mx.group(1)
        for root, _dirs, files in os.walk(path):
            for name in files:
                fpath = os.path.join(root, name)
                if parseFile(data, fpath, findall=True) == True:
                    results.append(fpath)
        return ["SUCCESS"] + results

def compute_time(fn, *args):
    t1 = time.time()
    result = fn(*args)
    t2 = time.time()
    t = int(math.ceil(2*(t2 - t1)))
    if t < TIME_LIMIT:
        t = TIME_LIMIT
    return t, result

def makeRandomFiles(data, count, dirs):
    allFiles = []
    for _i in range(count):
        crtDir = dirs[random.randint(0, len(dirs)-1)]
        newFile = os.path.join(crtDir, b"%s.%s" % (genRandomName(), genRandomName(3)))
        while newFile in allFiles:
            newFile += genRandomName(1)
        allFiles.append(newFile)
    for fpath in allFiles:
        genSectionFile(fpath, data)
    return allFiles


def makeCorruptedFiles(data, path):
    nrCorrupted = 3
    dirPath = os.path.join(path, b"_corrupted")
    os.mkdir(dirPath)
    allFiles = []
    for _i in range(nrCorrupted * 4):
        newFile = os.path.join(dirPath, b"%s.%s" % (genRandomName(), genRandomName(3)))
        while newFile in allFiles:
            newFile += genRandomName(1)
        allFiles.append(newFile)
    allFiles.sort()
    for i in range(nrCorrupted):
        genSectionFile(allFiles[4*i], data, wrongMagic=True)
        genSectionFile(allFiles[4*i+1], data, wrongVersion=True)
        genSectionFile(allFiles[4*i+2], data, wrongSectNr=True)
        genSectionFile(allFiles[4*i+3], data, wrongSectTypes=True)
    return allFiles

def makeHugeFiles(data, path):
    dirPath = os.path.join(path, b"_huge")
    os.mkdir(dirPath)
    allFiles = []
    for _i in range(2):
        newFile = os.path.join(dirPath, b"%s.%s" % (genRandomName(), genRandomName(3)))
        while newFile in allFiles:
            newFile += genRandomName(1)
        allFiles.append(newFile)
    for fname in allFiles:
        genSectionFile(fname, data, hugeLines=True)
    return allFiles


def buildTestFs(data):
    ROOT_NAME = b"test_root"
    if os.path.isdir(ROOT_NAME):
        shutil.rmtree(ROOT_NAME)
    dirs = makeRandomDirs(ROOT_NAME, 100)
    files = makeRandomFiles(data, 200, dirs)
    corrupted = makeCorruptedFiles(data, ROOT_NAME)
    huge = makeHugeFiles(data, ROOT_NAME)
    return dirs, files, corrupted, huge

def shuffle(l):
    n = len(l)
    for _k in range(100*n):
        i = random.randint(0, n-1)
        j = random.randint(0, n-1)
        aux = l[i]
        l[i] = l[j]
        l[j] = aux

def getSizeInterval(items):
    sizes = [os.path.getsize(x) for x in items if os.path.isfile(x)]
    if len(sizes) < 3:
        return None, None
    return min(sizes), max(sizes)

def generateTests(data):
    random.seed(data["variant"] + data["name"])
    dirs, files, corrupted, huge = buildTestFs(data)
    tests = []
    # variant
    tests.append([  "variant", # test name
                    ["variant"], # command
                    TIME_LIMIT, # timelimit
                    [data["variant"]], # expected output
                    False, # disregard line order
                ])
    # simple listing
    dirs1 = dirs[:]
    shuffle(dirs1)
    count = 0
    for path in dirs1:
        cmd = ["list", "path=%s" % path.decode()]
        timeLimit, result = compute_time(perform_a1, data, cmd)
        if (count < 4 and len(result) > 0) or len(result) > 2:
            count += 1
            tests.append([  "simple_listing_%d" % count,
                            cmd,
                            timeLimit,
                            result,
                            True
                ])
            if count >= 5:
                break

    # recursive listing
    dirs1 = dirs[:]
    shuffle(dirs1)
    dirs1.remove(dirs[0])
    dirs1.insert(0, dirs[0])
    count = 0
    for path in dirs1:
        cmd = ["list", "recursive", "path=%s" % path.decode()]
        timeLimit, result = compute_time(perform_a1, data, cmd)
        if (count < 4 and len(result) > 0) or len(result) > 2:
            count += 1
            tests.append([  "recursive_listing_%d" % count,
                            cmd,
                            timeLimit,
                            result,
                            True
                ])
            if count >= 5:
                break

    # filtered listing
    dirs1 = dirs[:]
    shuffle(dirs1)
    countSize = 0
    countName = 0
    countPerm = 0
    for path in dirs1:
        if countSize < 6 and (data["filter_size_greater"] or data["filter_size_smaller"]):
            if data["filter_size_greater"]:
                filter = "size_greater"
            else:
                filter = "size_smaller"
            minSize, maxSize = getSizeInterval([os.path.join(path, x) for x in os.listdir(path)])
            if minSize is not None:
                size = random.randint(minSize, maxSize)
                cmd = ["list", "%s=%d" % (filter, size), "path=%s" % path.decode()]
                if countSize % 2 == 1:
                    cmd.insert(random.randint(1, 2), "recursive")
                timeLimit, result = compute_time(perform_a1, data, cmd)
                if len(result) > 1:
                    countSize += 1
                    tests.append([  "%s_%d" % (filter, countSize),
                                    cmd,
                                    timeLimit,
                                    result,
                                    True
                        ])
        if countName < 6 and (data["filter_name_starts_with"] or data["filter_name_ends_with"]):
            names = os.listdir(path)
            if len(names) >= 3:
                sample = names[random.randint(0, len(names)-1)]
                if data["filter_name_starts_with"]:
                    filter = "name_starts_with"
                    substr = sample[:random.randint(1, 4)]
                else:
                    filter = "name_ends_with"
                    substr = sample[-random.randint(2, 4):]
                substr = substr.decode()
                cmd = ["list", "%s=%s" % (filter, substr), "path=%s" % path.decode()]
                if countSize % 2 == 1:
                    cmd.insert(random.randint(1, 2), "recursive")
                timeLimit, result = compute_time(perform_a1, data, cmd)
                if len(result) > 1:
                    countName += 1
                    tests.append([  "%s_%d" % (filter, countName),
                                    cmd,
                                    timeLimit,
                                    result,
                                    True
                        ])
        if countPerm < 6 and (data["filter_permissions"] or data["filter_has_perm_execute"] or data["filter_has_perm_write"]):
            names = os.listdir(path)
            if len(names) >= 2:
                if data["filter_permissions"]:
                    filter = "permissions"
                    sample = names[random.randint(0, len(names)-1)]
                    perm = get_perm(os.path.join(path, sample))
                    cmd = ["list", "permissions=%s" % perm, "path=%s" % path.decode()]
                    if countSize % 2 == 1:
                        cmd.insert(random.randint(1, 2), "recursive")
                else:
                    if data["filter_has_perm_execute"]:
                        filter = "has_perm_execute"
                    else:
                        filter = "has_perm_write"
                    cmd = ["list", filter, "path=%s" % path.decode()]
                    if countSize % 2 == 1:
                        cmd.insert(random.randint(1, 2), "recursive")
                timeLimit, result = compute_time(perform_a1, data, cmd)
                if len(result) > 1:
                    countPerm += 1
                    tests.append([  "%s_%d" % (filter, countPerm),
                                    cmd,
                                    timeLimit,
                                    result,
                                    True
                        ])
    # parsing section files
    files1 = files[:]
    shuffle(files1)
    files1 = files1[:10]
    for count, path in enumerate(files1):
        cmd = ["parse", "path=%s" % path.decode()]
        timeLimit, result = compute_time(perform_a1, data, cmd)
        tests.append([  "parse_%d" % (count+1),
                                cmd,
                                timeLimit,
                                result,
                                False
                    ])
    # corrupted files
    for count, path in enumerate(corrupted):
        cmd = ["parse", "path=%s" % path.decode()]
        timeLimit, result = compute_time(perform_a1, data, cmd)
        tests.append([  "corrupted_%d" % (count+1),
                                cmd,
                                timeLimit,
                                result,
                                False
                    ])

    # extracting lines
    files1 = files[:]
    shuffle(files1)
    files1 = files1[:10] + huge
    for count, path in enumerate(files1):
        sectNr, lineNr = parseFile(data, path, randomLine=True)
        cmd = ["extract", "path=%s" % path.decode(), "section=%d" % sectNr, "line=%d" % lineNr]
        timeLimit, result = compute_time(perform_a1, data, cmd)
        tests.append([  "extract_%d" % (count+1),
                                cmd,
                                timeLimit,
                                result,
                                False
                    ])

    # findall
    dirs1 = dirs[:]
    shuffle(dirs1)
    dirs1.remove(dirs[0])
    dirs1.insert(0, dirs[0])
    count = 0
    for path in dirs1:
        cmd = ["findall", "path=%s" % path.decode()]
        timeLimit, result = compute_time(perform_a1, data, cmd)
        if len(result) > 0:
            count += 1
            tests.append([  "findall_%d" % count,
                            cmd,
                            timeLimit,
                            result,
                            True
                ])
            if count >= 8:
                break


    #save tests to file
    fout = open("tests.json", "w")
    json.dump(tests, fout, indent=4)
    fout.close()
    return tests

def compile():
    if os.path.isfile(A1_PROG):
        os.remove(A1_PROG)
    compLog = open(COMPILE_LOG_FILE_NAME, "w")
    cmd = ["gcc", "-Wall", "%s.c" % A1_PROG]
    if os.path.isfile("companion.c"):
        cmd.append("companion.c")
    cmd += ["-o", A1_PROG]
    subprocess.call(cmd, stdout=compLog, stderr=compLog)
    compLog.close()
    if os.path.isfile(A1_PROG):
        compLog = open(COMPILE_LOG_FILE_NAME)
        logContent = compLog.read()
        compLog.close()
        if "warning" in logContent:
            return 1
        return 2
    else:
        return 0

def loadTests():
    if os.path.isfile("tests.json"):
        fin = open("tests.json")
        tests = json.load(fin)
        fin.close()
    else:
        with open("a1_data.json") as a1_data:
            content = a1_data.read()
            decoded_data = base64.b64decode(content).decode('utf-8')
            data = json.loads(decoded_data)

        print("Running tester for the first time.")
        print("Generating tests cases (this may take a while)...")
        tests = generateTests(data)
    return tests

def checkValgrind():
    global VALGRIND
    try:
        subprocess.call(["valgrind"], stdout=open(os.devnull, "w"), stderr=open(os.devnull, "w"))
        print("valgrind found")
    except OSError as e:
        if e.errno == errno.ENOENT:
            VALGRIND = False
            print("valgrind not found. for accurate results, please install it.")

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
        RX_USEFUL_FILE = re.compile(r".*(?:\.py)|(?:\.c)|(?:_data\.json)$")
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
    global VALGRIND
    args = sys.argv[1:]
    if "docker" in args:
        if not DOCKER_AVAILABLE:
            print("\033[1;31mPlease install the docker module for Python")
            sys.exit()
        args.remove("docker")
        dh = DockerHelper()
        dh.runContainer()
        dh.copyDir(".")
        logFile = open("tester_docker.log", "w")
        res = dh.execute(["python3", "tester.py"] + args)
        logFile.write(res)
        logFile.close()
        dh.copyCompileLogFileInCurrentDirectory()
        dh.removeContainer()
        print(res)
    else:
        if "valgrind" in args:
            VALGRIND = True
            checkValgrind()
        tests = loadTests()

        compileRes = compile()
        if compileRes == 0:
            print("COMPILATION ERROR")
        else:
            score = 0
            maxScore = 0
            for t in tests:
                tester = Tester(t[0], t[1], t[2], t[3], t[4])
                score += tester.perform()
                maxScore += 1
            print("Total score: %d / %d" % (score, maxScore))
            score = 100.0 * score / maxScore
            if compileRes == 1:
                print("\033[1;31mThere were some compilation warnings. A 10% penalty will be applied.\033[0m")
                score = score * 0.9
            if Tester.leaks:
                print("\033[1;31mThere were some memory leaks. A 10% penalty will be applied.\033[0m")
                score = score * 0.9
            print("Assignment grade: %.2f / 100" % score)

if __name__ == "__main__":
    main()