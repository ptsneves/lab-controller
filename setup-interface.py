#!/usr/bin/env python3

import subprocess
import io
import os
import sys
import stat
import shutil
import time
import argparse


def runProcess(command):
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    process.wait()
    print(command)
    return {"ret": process.returncode,
        "command": command,
        "stdout": io.TextIOWrapper(process.stdout, encoding='utf-8').readlines(),
        "stderr" : io.TextIOWrapper(process.stderr, encoding='utf-8').readlines()}

def isZeroExitCode(process):
    return True if process["ret"] == 0 else False

def doesCommandExist(command):
    return shutil.which(command)

def doesNMInterfaceExist(interface):
    result = runProcess("nmcli device status")
    if not isZeroExitCode(result):
        raise Exception("nmcli should not fail when checking global status. Error:\n{}".format(result["stderr"]))

    for line in result["stdout"]:
        if interface in line:
            return True
    return False

def isNMInterfaceManaged(interface):
    if not doesNMInterfaceExist(interface):
        raise Exception("Network Manager Interface {} does not exist".format(interface))

    result = runProcess("nmcli device show {}".format(interface))
    if not isZeroExitCode(result):
        raise Exception("nmcli device show {} failed with error:\n{}".format(interface, result["stderr"]))

    for line in result["stdout"]:
        if "GENERAL.STATE:" in line:
            if "unmanaged" in line:
                return False
            else:
                return True

    raise Exception("Could not find the General state of the interface {}".format(interface))

def doesIPInterfaceExist(interface):
    res = runProcess("ip link show {}".format(interface))
    return isZeroExitCode(res)

def isIPInterfaceUp(interface):
    res = runProcess("ip link show {}".format(interface))
    for line in res["stdout"]:
        if 'state DOWN' in line:
            return False
        elif 'state UP' in line:
            return True

    raise Exception("Could not determine state of interface")

def bringIPInterfaceUp(interface):
    if isIPInterfaceUp(interface):
        raise Exception("Cannot bring up interface {} because it is already configured.".format(interface))

    res = runProcess("ip link set {} up".format(interface))
    if not isZeroExitCode(res):
        raise Exception("Error bringing interface {} up. Error\n{}".format(interface, res["stderr"]))

def flushIPInterface(interface):
    res = runProcess("ip addr flush dev {}".format(interface))
    if not isZeroExitCode(res):
        raise Exception("Error flusing interface {}. Error\n{}".format(interface, res["stderr"]))

def bringIPInterfaceDown(interface):
    res = runProcess("ip link set {} down".format(interface))
    if not isZeroExitCode(res):
        raise Exception("Failed to set interface {} down. Error\n{}".format(interface, res["stderr"]))

def configureIPInterface(interface, ip, broadcast_ip=None):
    cmd_string = ""
    if broadcast_ip:
        cmd_string = "ip addr add {} scope global broadcast {} dev {}".format(ip, broadcast_ip, interface)
    else:
        cmd_string = "ip addr add {}  scope global dev {}".format(
            ip, interface)

    res = runProcess(cmd_string)
    if not isZeroExitCode(res):
        raise Exception("Error configuring interface {}. Error thrown in ip\n{}\n{}".format(
            interface, cmd_string, res["stderr"]))

def isAcceptablePythonVersion(major, minor):
    return sys.version_info[0] == major and sys.version_info[1] > minor

def doesCommandHaveSUID(command):
    abs_path = shutil.which(command)
    cmd_stat = os.stat(abs_path)
    return (cmd_stat.st_mode & stat.S_ISUID) != 0

def doesIPHaveSUID():
    return doesCommandHaveSUID('ip')

def isIPV4ForwardingEnabled():
    res = runProcess('sysctl net.ipv4.ip_forward')
    if not isZeroExitCode(res):
        raise Exception("Could not run sysctl?. {} Error:\n{}".format(
            res["command"], res["stderr"]))

    result = None
    for line in res["stdout"]:
        print(line)
        if "net.ipv4.ip_forward = 1" in line:
            return True
        elif "net.ipv4.ip_forward = 0" in line:
            return False

    raise Exception(
        "Did not find forwarding information in {}".format(res["command"]))

def setSYSCTLIPV4Forwarding():
    if not isIPV4ForwardingEnabled():
        if not doesCommandHaveSUID('sysctl'):
            raise Exception(
                "Could not turn on ipv4 forwarding. Please set suid in sysctl \
                    or add net.ipv4.ip_forward = 1 to /etc/sysctl.conf")
        else:
            if not isZeroExitCode("sysctl -w net.ipv4.ip_forward = 1"):
                raise Exception("Failed to set ipv4 forwarding on")

def getGatewayDevice():
    res = runProcess("ip route show default")
    if not isZeroExitCode(res):
        raise Exception("Could not retrieve default route. Error:\n{}".format(res["stderr"]))

    split = res["stdout"][0].split()
    for i in range(0, len(split)):
        if split[i] == "dev" and i + 1 < len(split):
            return split[i + 1]
    
    raise Exception("Could not find default gateway device")

def setIPTablesNat():
    gw_interface = getGatewayDevice()
    res = runProcess("iptables -t nat -A POSTROUTING -o {} -j MASQUERADE".format(gw_interface))
    if not isZeroExitCode(res):
        raise Exception("Could not set iptables forwarding NAT. Command\n{}\n{}".format(res["command"], res["stderr"]))

def configureInterfaceUp(args):
    if doesCommandExist("nmcli"):
        if isNMInterfaceManaged(args.interface):
            raise Exception("Interface {} is managed by network manager and we cannot work with that, \
                as we do not want to touch user leve stuff")
    attempts=0
    while attempts <= 3:
        if doesIPInterfaceExist(args.interface):
            if not isIPInterfaceUp(args.interface):
                bringIPInterfaceUp(args.interface)


            flushIPInterface(args.interface)
            configureIPInterface(args.interface, args.ip, args.broadcast_ip)
            setSYSCTLIPV4Forwarding()
            setIPTablesNat()
            return
        else:
            attempts += 1
            print("trying again attempt {}/3".format(attempts))
            time.sleep(2)

    raise Exception("IP Interface does not exist")

def configureInterfaceDown(args):
    print(args)
    if doesCommandExist("nmcli"):
        if isNMInterfaceManaged(args.interface):
            raise Exception("Interface {} is managed by network manager and we cannot work with that, \
                as we do not want to touch user leve stuff ")
    
    if doesIPInterfaceExist(args.interface):
        bringIPInterfaceDown(args.interface)
        flushIPInterface(args.interface)

if __name__ == '__main__':
    #shutil.which
    if not isAcceptablePythonVersion(3, 3):
        raise Exception("We need at least Python 3.3")

    if not doesIPHaveSUID():
        raise Exception("We need suid for ip to bring interfaces up. Try chmod u+s /bin/ip")


    if not doesCommandExist("ip"):
        raise Exception("To configure the interfaces the ip command must exist, which is not the case")

    parser = argparse.ArgumentParser(description="A program to setup interfaces of boards.")
    parser.add_argument('interface', nargs='?', help="The interface name to setup.")
    subparsers = parser.add_subparsers(help='Bring up or down')
    parser_up = subparsers.add_parser('up', help = "Options to bring interface up")
    parser_up.add_argument('ip', nargs='?', help="The ip address for the interface to setup.")
    parser_up.add_argument('broadcast_ip', nargs='?', help="The broadcast ip for the interface to setup.")
    parser_up.set_defaults(func=configureInterfaceUp)

    parser_down = subparsers.add_parser('down', help="Bring it down")
    parser_down.set_defaults(func=configureInterfaceDown)

    args = parser.parse_args()
    args.func(args)
