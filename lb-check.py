#!/usr/bin/python3

# -*- coding: utf-8 -*-

import csv
import os
import sys
import socket
import requests
from optparse import OptionParser

verbose = False


class Colors:
    HEADER = '\033[95m'
    OK_GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    END = '\033[0m'


class IpRanges:
    """To parse IP ranges, supported pattern:
        192.168.1.5
        192.168.1.5,192.168.1.6
        192.168.1.[5:6],192.168.1.10
        192.168.1.[5:6],192.168.1.[20:23]
      An array of IP list will be returned
    """

    def __init__(self, ranges):
        self.ranges = ranges

    @staticmethod
    def is_range(ip):
        return ':' in ip

    @staticmethod
    def range_to_list(ip_range): 
        ips = []
        prefix = ip_range[:ip_range.index('[')]
        range_from = ip_range[ip_range.index('[') + 1: ip_range.index(':')]
        range_to = ip_range[ip_range.index(':') + 1: ip_range.index(']')]
        for i in range(int(range_from), int(range_to) + 1):
            ips.append(prefix + str(i))

        return ips

    def parse(self):
        result = []
        items = self.ranges.split(',')
        for item in items:
            if self.is_range(item.strip()):
                result.extend(self.range_to_list(item.strip()))
            else:
                result.append(item.strip())

        return result


class Endpoint:

    def __init__(self, ip, port):
        self.ip = ip
        self.port = port


class HealthCheck:

    def __init__(self, url, auth=""):
        self.url = url
        self.auth = auth


class LoadBalancer:

    def __init__(self, name, frontend, backends, health_check):
        self.name = name
        self.frontend = frontend
        self.backends = backends
        self.health_check = health_check

    @classmethod
    def parse(cls, row):
        name, frontend_ip, frontend_port, health_check_url, backend_ip_ranges, backend_port, health_check_auth = row

        health_check = HealthCheck(health_check_url.strip(), health_check_auth.strip())
        frontend = Endpoint(frontend_ip.strip(), frontend_port.strip())

        backends = []

        for ip in IpRanges(backend_ip_ranges.strip()).parse():
            backends.append(Endpoint(ip, backend_port.strip()))

        return cls(name.strip(), frontend, backends, health_check)


class Status(object):
    L4_PASS = "L4:P"
    L7_PASS = "L7:P"
    L4_FAILED = "L4:F"
    L7_FAILED = "L7:F"


def telnet(ip, port):
    """check telnet works"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((ip, int(port)))
        if result == 0:
            return Status.L4_PASS
        else:
            return Status.L4_FAILED
        sock.close()
    except socket.timeout:
        return Status.L4_FAILED


def http_get(ip, port, url, auth):
    """check http get works"""
    try:
        if auth:
            username = auth[0:auth.index(":")]
            password = auth[auth.index(":") + 1:]
            r = requests.get('http://' + ip + ":" + port + url, auth=(username, password), timeout=3)
        else:
            r = requests.get('http://' + ip + ":" + port + url, timeout=3)

        if r.ok:
            return Status.L7_PASS
        else:
            return Status.L7_FAILED
    except requests.exceptions.RequestException:
        return Status.L7_FAILED


def column_width():
    if verbose:
        return {"Name": 30, "Frontend IP": 14, "Frontend Port": 13, "Frontend Status": 15, "Backend IP": 14,
                "Backend Port": 12, "Backend Status": 14, "Health Check": 50, "Auth": 22}
    else:
        return {"Name": 30, "Frontend IP": 14, "Frontend Port": 13, "Frontend Status": 15, "Backend IP": 14,
                "Backend Port": 12, "Backend Status": 14}


def print_empty_line():
    """print ---+---- line"""
    sys.stdout.write('+')

    for col, col_width in column_width().items():
        width = col_width + 1
        for _ in range(width):
            sys.stdout.write('-')

        sys.stdout.write('+')
    print('')


def print_column(col, col_width):
    print('{0:{width}}'.format(col, width=col_width), "|", end="")


def print_header():
    sys.stdout.write(Colors.HEADER)
    sys.stdout.write('|')
    for name, width in column_width().items():
        print_column(name, width)
    print("")
    sys.stdout.write(Colors.END)


def print_lb_status(name, frontend_ip, frontend_port, frontend_status, backend_ip, backend_port, backend_status,
                    health_check, auth):
    sys.stdout.write('|')
    print_column(name, column_width()["Name"])
    print_column(frontend_ip, column_width()["Frontend IP"])
    print_column(frontend_port, column_width()["Frontend Port"])

    frontend_status_format = ",".join(frontend_status)
    if "L4:P,L7:P" == frontend_status_format or "L4:P" == frontend_status_format:
        sys.stdout.write(Colors.OK_GREEN)
        print_column("passing", column_width()["Frontend Status"])
        sys.stdout.write(Colors.END)
    else:
        sys.stdout.write(Colors.WARNING)
        print_column(frontend_status_format, column_width()["Frontend Status"])
        sys.stdout.write(Colors.END)

    print_column(backend_ip, column_width()["Backend IP"])
    print_column(backend_port, column_width()["Backend Port"])

    backend_status_format = ",".join(backend_status)
    if "L4:P,L7:P" == backend_status_format or "L4:P" == backend_status_format:
        sys.stdout.write(Colors.OK_GREEN)
        print_column("passing", column_width()["Backend Status"])
        sys.stdout.write(Colors.END)
    else:
        sys.stdout.write(Colors.WARNING)
        print_column(backend_status_format, column_width()["Backend Status"])
        sys.stdout.write(Colors.END)

    if verbose:
        print_column(health_check, column_width()["Health Check"])
        print_column(auth, column_width()["Auth"])

    print("")


def check(file):
    with open(file, newline="") as csv_file:
        rows = csv.reader(csv_file, delimiter='|', quotechar='"')
        next(rows)

        print_header()
        print_empty_line()
        for row in rows:
            if row:
                lb = LoadBalancer.parse(row)
                frontend_status = [telnet(lb.frontend.ip, lb.frontend.port)]
                if lb.health_check.url:
                    frontend_status.append(http_get(lb.frontend.ip, lb.frontend.port, lb.health_check.url, lb.health_check.auth))

                for index, backend in enumerate(lb.backends):
                    backend_status = [telnet(backend.ip, backend.port)]
                    if lb.health_check.url:
                        backend_status.append(http_get(backend.ip, backend.port, lb.health_check.url, lb.health_check.auth))

                    if not verbose:
                        if index == 0:
                            print_lb_status(lb.name, lb.frontend.ip, lb.frontend.port, frontend_status, backend.ip,
                                            backend.port, backend_status, lb.health_check.url, lb.health_check.auth)
                        else:
                            print_lb_status("", "", "", "", backend.ip, backend.port, backend_status, "", "")
                    else:
                        print_lb_status(lb.name, lb.frontend.ip, lb.frontend.port, frontend_status, backend.ip,
                                        backend.port, backend_status, lb.health_check.url, lb.health_check.auth)


def set_verbose(v):
    global verbose
    verbose = v


def main():
    parser = OptionParser()
    parser.add_option("-f", dest="filename", default=os.path.dirname(sys.argv[0]) + "/lb.csv",
                      help="lb csv file, default one is lb.csv")
    parser.add_option("-v", action="store_true", dest="verbose", default=False, help="print all information to stdout")

    (options, args) = parser.parse_args()
    set_verbose(options.verbose)

    check(options.filename)


if __name__ == '__main__':
    main()
