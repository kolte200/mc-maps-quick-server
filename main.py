#!/usr/bin/python3

import json
import http.server
import socketserver
import urllib.request
import os
import socket
import shutil
import subprocess
import sys
import threading
import time


WEB_PORT = 8080
WEB_ROOT = "www"
WEB_INTERFACE = "0.0.0.0"

CONFIG_FILENAME = "config.json"
RC_FILENAME = "ressources.zip"
TMP_DIRNAME = "tmp"


class HttpServerHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_ROOT, **kwargs)


__stop_http_server = False

def run_http_server():
    with socketserver.TCPServer((WEB_INTERFACE, WEB_PORT), HttpServerHandler) as httpd:
        print("Serving HTTP server on port %i" % WEB_PORT)
        httpd.timeout = 0.02
        while not __stop_http_server:
            httpd.handle_request()

def stop_http_server():
    global __stop_http_server
    __stop_http_server = True
    print("Stop HTTP server")


def download_file(url : str, filename : str) -> None:
    path, rep = urllib.request.urlretrieve(url, filename)


def get_local_ip() -> str:
    hostname = socket.gethostname()
    return socket.gethostbyname(hostname)


def get_rc_dl_url(filename : str) -> str:
    return "http://%s:%i/%s" % (get_local_ip(), WEB_PORT, filename)


def find_mc_world_folder(basefolder : str) -> str:
    files = os.listdir(basefolder)
    if "level.dat" in files:
        return basefolder
    for file in files:
        fullpath = os.path.join(basefolder, file)
        if os.path.isdir(fullpath):
            r = find_mc_world_folder(fullpath)
            if r is not None:
                return r
    return None


def remove_mc_color_codes(s : str) -> str:
    r = ""
    d = False
    for c in s:
        if d:
            d = False
        else:
            if c == '§':
                d = True
            else:
                r += c
    return r


str_to_filename_table = str.maketrans({
    ' ': '-',
    '/': '-',
    '\\': '-',
    '&': '-',
    ',': '-',
    ';': '-',
    '=': '-',
    ':': '-'
})

def str_to_filename(s : str) -> str:
    return remove_mc_color_codes(s.lower().translate(str_to_filename_table))


class McPropertiesParser:
    def __init__(self) -> None:
        self.entries = {}
        self.lines = []

    def load(self, filename):
        lines = None
        with open(filename, 'r') as file:
            lines = file.readlines()
        lasti = len(lines) - 1
        for i in range(len(lines)):
            line = lines[i]
            if len(line) == 0 or line.lstrip().startswith("#"):
                self.lines.append((0, line))
                continue
            pos = line.find('=')
            if pos == -1:
                raise Exception("No '=' on the line '%s'" % line)
            rawkey = line[:pos]
            key = rawkey.strip()
            value = line[pos+1:(-1 if i < lasti else 0)]
            if key in self.entries:
                raise Exception("The entry '%s' is repeated" % key)
            self.entries[key] = len(self.lines)
            self.lines.append((1, rawkey, value))

    def save(self, filename):
        with open(filename, 'w') as file:
            lasti = len(self.lines) - 1
            for i in range(len(self.lines)):
                line = self.lines[i]
                if line[0] == 0:
                    file.write(line[1])
                else:
                    file.write("%s=%s" % (line[1], line[2]))
                    if i < lasti: file.write('\n')

    def get(self, key):
        if key not in self.entries: return None
        return self.lines[self.entries[key]][2]

    def set(self, key, value):
        if key in self.entries:
            i = self.entries[key]
            self.lines[i] = (1, self.lines[i][1], value)
        else:
            self.lines.append((1, key, value))


class Version:
    def __init__(self, version = None) -> None:
        self.numbers = None
        self.generic = None
        if version is not None:
            self.parse(version)

    def parse(self, version):
        parts = version.split('.')
        self.generic = False
        self.numbers = []
        for part in parts:
            if part == '*':
                self.generic = True
                break
            self.numbers.append(int(part))

    def __eq__(self, o: object) -> bool:
        if not isinstance(o, Version):
            raise Exception("You can only compare a Version with another Version object")
        if self.generic != o.generic:
            return False
        if len(self.numbers) != len(o.numbers):
            return False
        for i in range(len(self.numbers)):
            if self.numbers[i] != o.numbers[i]:
                return False
        return True

    def __contains__(self, o : object) -> bool:
        if not isinstance(o, Version):
            raise Exception("The right operand of 'in' must be a Version object here")
        om = len(o.numbers)
        sm = len(self.numbers)
        if om < sm or (not self.generic and om != sm):
            return False
        for i in range(min(om, sm)):
            if self.numbers[i] != o.numbers[i]:
                return False
        return True

    def __gt__(self, o : object) -> bool:
        if not isinstance(o, Version):
            raise Exception("You can only compare a Version with another Version object")
        for i in range(min(len(self.numbers), len(o.numbers))):
            if self.numbers[i] > o.numbers[i]:
                return True
            elif self.numbers[i] < o.numbers[i]:
                return False
        return False

    def __lt__(self, o : object) -> bool:
        if not isinstance(o, Version):
            raise Exception("You can only compare a Version with another Version object")
        for i in range(min(len(self.numbers), len(o.numbers))):
            if self.numbers[i] < o.numbers[i]:
                return True
            elif self.numbers[i] > o.numbers[i]:
                return False
        return False

    def __ge__(self, o : object) -> bool:
        return self.__eq__(o) or self.__gt__(o)

    def __le__(self, o : object) -> bool:
        return self.__eq__(o) or self.__lt__(o)

    def __ne__(self, o : object) -> bool:
        return not self.__eq__(o)


class Versions:
    def __init__(self, expression : str = None) -> None:
        self.ranges = []
        if expression is not None:
            self.parse(expression)

    def parse(self, expression : str) -> None:
        parts = expression.split(',')
        for part in parts:
            edges = part.split('-')
            if len(edges) > 2:
                raise Exception("Invalid range syntax for '%s'" % part)
            v1 = Version(edges[0])
            if len(edges) == 1:
                self.ranges.append((v1, v1))
            else:
                v2 = Version(edges[1])
                self.ranges.append((v1, v2))

    def has(self, version : Version) -> bool:
        for v1, v2 in self.ranges:
            if version in v1 or version in v2 or (version > v1 and version < v2):
                return True
        return False

    def __contains__(self, o : object) -> bool:
        if not isinstance(o, Version):
            raise Exception("The right operand of 'in' must be a Version object here")
        return self.has(o)



if __name__ == "__main__":
    # Read config file
    config_file = open(CONFIG_FILENAME, "r")
    config_text = config_file.read()
    config_file.close()
    config_json = json.loads(config_text)

    print("Maps:")
    i = 1
    for m in config_json['maps']:
        print("  %i : %s" % (i, m['name']))
        i += 1

    rep = int(input("Please enter the map ID : "))
    m = config_json['maps'][rep - 1]
    print()


    print("==== Preparing the server for the map %s ====" % m['name'])
    print()

    # Choose a Minecraft version
    mc = None
    for key in config_json['mc_versions'].keys():
        if Version(m['mc_version']) in Versions(key):
            mc = config_json['mc_versions'][key]
            print("Selecting Minecraft version '%s'" % key)
            break
    if mc is None:
        raise Exception("Can't find a proper Minecraft version in config")

    # Choose a Java version
    java = None
    for key in config_json['java_versions'].keys():
        if Version(mc['java_version']) in Versions(key):
            java = config_json['java_versions'][key]
            print("Selecting Java version '%s'" % key)
    if java is None:
        raise Exception("Can't find a proper Java version in config")

    # Check and download the Minecraft jar
    mc_filename = mc['file']
    url = mc['url']
    if os.path.isfile(mc_filename):
        print("Minecraft jar file '%s' already exists" % mc_filename)
    else:
        print("Minecraft jar file '%s' don't exists, downloading ..." % mc_filename)
        download_file(url, mc_filename)
        if not os.path.isfile(mc_filename):
            raise Exception("Failled to download Minecraft jar from url '%s'" % url)
        print("Download finished")

    # Copy (and zip if needed) the ressourcepack to a tempory location
    rc_filename : str = None
    if 'ressourcepack_path' in m and m['ressourcepack_path']:
        path : str = m['ressourcepack_path']
        rc_filename = os.path.join(WEB_ROOT, RC_FILENAME)
        if path.endswith(".zip") and os.path.isfile(path):
            shutil.copyfile(path, rc_filename)
        else:
            shutil.make_archive(rc_filename, 'zip', path)

    # Copy map
    reset_map = True
    map_dirname = str_to_filename(m['name'])
    if os.path.isdir(map_dirname):
        reset_map = False
        print("Map folder '%s' already exists. You can:" % map_dirname)
        print("  1 : Don't touch to anything")
        print("  2 : Delete all player's data")
        print("  3 : Reset the map")
        print("  4 : Abort this program")
        rep = int(input("What do you want to do ? : "))
        if rep == 2:
            playerdata_dirname = os.path.join(map_dirname, "playerdata")
            for player_filename in os.listdir(playerdata_dirname):
                if os.path.isfile(player_filename):
                    os.remove(os.path.join(playerdata_dirname, player_filename))
        elif rep == 3:
            reset_map = True
            shutil.rmtree(map_dirname)
        elif rep == 4:
            print("Program aborted")
            exit(0)
    else:
        print("Copying map folder '%s'" % map_dirname)

    if reset_map:
        path : str = m['world_path']
        if os.path.isdir(path):
            shutil.copytree(find_mc_world_folder(path), map_dirname)
        elif path.endswith(".zip") and os.path.isfile(path):
            tmp_dirname = os.path.join(TMP_DIRNAME, "world")
            if not os.path.isdir(tmp_dirname):
                os.makedirs(tmp_dirname)
            shutil.unpack_archive(path, tmp_dirname)
            os.rename(find_mc_world_folder(tmp_dirname), map_dirname)

    # Edit server.properties file
    properties = McPropertiesParser()
    properties.load("server.properties")
    if rc_filename is not None:
        properties.set('require-resource-pack', 'true')
        properties.set('resource-pack', get_rc_dl_url(RC_FILENAME))
    else:
        properties.set('require-resource-pack', 'false')
        properties.set('resource-pack',  "")
    properties.set('level-name', map_dirname)
    properties.save("server.properties")

    print()
    print("==== Starting server on Minecraft %s ====" % m['mc_version'])
    print()

    args = []
    args.append(os.path.join(java['home'], "bin", "java.exe"))
    if 'args' in java: args.extend(java['args'])
    args.extend(["-jar", mc_filename])
    if 'args' in mc: args.extend(mc['args'])

    http_thr = threading.Thread(target = run_http_server)
    http_thr.start()

    proc = subprocess.Popen(args, stderr=sys.stderr, stdout=sys.stdout, stdin=sys.stdin)
    try:
        while proc.poll() is None:
            time.sleep(0.02)
    except KeyboardInterrupt:
        proc.terminate()
    print()

    stop_http_server()
    http_thr.join()
