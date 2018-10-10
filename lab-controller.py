#!/usr/bin/env python3

import os
import sys
import argparse
import json
import pexpect

def intersect(l1, l2):
  expected_len = min(len(l1), len(l2))
  intersection_len = len(set(l1) & set(l2))
  return intersection_len == expected_len

def check_serial_settings(json_appliance_section):
  if not intersect(['device', 'baud'], json_appliance_section.keys()):
    raise RuntimeError("Make sure that 'device' and 'baud' settings are"
      " available in appliance section")

def check_applicance(appliance, json_conf):
  if appliance not in json_conf.keys():
    raise RuntimeError("appliance {} not found in configuration.".format(appliance))

def check_appliance_section(appliance_section, json_appliance):
  if appliance_section  not in json_appliance.keys():
    raise RuntimeError("Cannot find {} configurations".format(appliance_section))

def check_device_type(json_appliance_section):
  if 'type' not in json_appliance_section.keys():
    raise RuntimeError("type not defined in appliance section")

def do_power_group(group_json, action, global_json_conf):
  if "devices" not in group_json.keys():
    raise RuntimeError("Found a group with no devices. Please correct the type or add devices")

  for device in group_json["devices"]:
    do_power(device, action, global_json_conf)

def check_expect_instance(json_expect_instance):
  if not intersect(["text", "timeout"], json_expect_instance.keys()):
    raise RuntimeError("'text' and 'timeout' data is mandatory for each expect call")
  if not json_expect_instance["timeout"].isdigit():
    raise RuntimeError("'timeout' is not a number")

def check_json_expect(json_expect):
  if not "expect" in json_expect.keys():
    raise RuntimeError("At least one expect root key is required in json")

  json_expect_array = json_expect["expect"]
  for json_expect_instance in json_expect_array:
    check_expect_instance(json_expect_instance)

def check_usb_json(json_usb):
  if not intersect(['usb-address', 'usb-port'], json_usb):
    raise RuntimeError("'usb-address' and 'usb-port' are required for usb power control")

def check_io(json_command):
  if "io" not in json_command.keys():
    return

  if len(json_command["io"]) == 0:
    raise RuntimeError("io list needs to have at least one element")

def is_io_command(json_action_command):
  return "io" in json_action_command.keys()

def is_executable_command(json_action_command):
  return "execute" in json_action_command.keys()

def is_invalid_command(json_action_command):
  return not is_executable_command(json_action_command) and not is_io_command(json_action_command)

def check_command(json_communication):
  if not intersect(["command"], json_communication.keys()):
    raise RuntimeError("'command' dictionary not found in power configuration")

  if not intersect(['on', 'off'], json_communication['command'].keys()):
    raise RuntimeError("'on' or 'off' configurations were not found. Please add them")

  for action in json_communication['command'].keys():
    for json_action_command in json_communication['command'][action]:
      if is_invalid_command(json_action_command):
        raise RuntimeError("execute or io keys are mandatory for all actions")

      check_io(json_action_command)

def get_serial_cmd(device, baud):
  return "socat -t0 STDIO,raw,echo=0,escape=0x03,nonblock=1 " \
      "file:{},b{},cs8,parenb=0,cstopb=0,clocal=0,raw,echo=0".format(device, baud)

def do_execute(execute, shell = False):
  if shell:
    execute = "bash -c '{}'".format(execute)

  return pexpect.spawnu(execute, env = os.environ, codec_errors = 'ignore')

def do_expect(conn, expect = None, match_type = None, timeout = 2):
  if expect:
    if match_type == "exact":
      conn.expect_exact(expect, timeout)
    else:
      conn.expect(expect, timeout = int(timeout))

def do_send(conn, text = None):
  if text:
    conn.send(text)

def do_host_command(action_json):
  if "execute" not in action_json.keys():
    raise RuntimeError("'execute' directive required for command")

  exec_conn = do_execute(action_json["execute"])
  for io in action_json["io"]:
    if "send" in io.keys():
      do_send(exec_conn, io["send"])

    if "expect" in io.keys():
      expect = io["expect"]
      text = expect["text"]

      match_type = None
      if "match-type" in expect:
        match_type = expect["match-type"]

      timeout = 2
      if "timeout" in expect:
        timeout = expect["timeout"]

      do_expect(exec_conn, text, match_type, timeout)

  if not exec_conn.isalive() and exec_conn.wait() != 0:
    raise RuntimeError("Host Command did not execute successfully: {}".format(execute))

def do_power_serial(action, json_power):
  check_serial_settings(json_power)
  check_command(json_power)

  power_cmd = get_serial_cmd(json_power['device'], json_power['baud'])

  for json_action_command in json_power['command'][action]:
    if "io" not in json_action_command.keys():
      raise RuntimeError("io section required for serial devices")

    check_io(json_action_command)

  json_action_command["execute"] = power_cmd
  do_host_command(json_action_command)

def do_power_usb(action, json_power):
  check_usb_json(json_power)

  execute = 'uhubctl -a {} -l {} -p {}'.format(action, json_power['usb-address'], json_power['usb-port'])

  io_list = []
  io_list.append({ "expect" : {"text" : 'Sent power {} request'.format(action)}})
  io_list.append({ "expect" : {"text" : 'New status for hub {}'.format(json_power['usb-address'])}})

  if action == "off":
    io_list.append({ "expect" : { "text" : '  Port {}: 0000 {}'.format(json_power['usb-port'], action)}})
  if action == "on":
    io_list.append({ "expect" : { "text" : '  Port {}: [0-9]{{4}} power'.format(json_power['usb-port'])}})
  json_action_command = {"execute" : execute, "io" : io_list}
  do_host_command(json_action_command)

def do_power_command(action, json_power):
  check_command(json_power)

  for json_action_command in json_power["command"][action]:
    do_host_command(json_action_command)

def do_power(appliance, action, json_conf):
  appliance_section = 'power'

  check_applicance(appliance, json_conf)
  json_appliance = json_conf[appliance]
  check_appliance_section(appliance_section, json_appliance)
  json_appliance_section = json_appliance[appliance_section]
  ran_power = False

  for json_communication_method in json_appliance_section:
    check_device_type(json_communication_method)
    if json_communication_method['type'] == 'serial':
      try:
        do_power_serial(action, json_communication_method)
        ran_power = True
      except RuntimeError as e:
        print(e)
    elif json_communication_method['type'] == 'usb':
      try:
        do_power_usb(action, json_communication_method)
        ran_power = True
      except RuntimeError as e:
        print(e)
    elif json_communication_method['type'] == 'host':
        do_power_command(action, json_communication_method)
        ran_power = True
    elif json_communication_method['type'] == 'group':
        do_power_group(json_communication_method, action, json_conf)
        ran_power = True
    else:
      raise RuntimeError("type {} is not supported".format(json_communication_method['type']))

  if not ran_power:
    raise RuntimeError("Did not successfully turn power on for appliance {}".format(appliance))

def get_serial_device(appliance, appliance_section, json_conf):
  found_serial = False
  device_data_result = None
  check_applicance(appliance, json_conf)
  json_appliance = json_conf[appliance]

  check_appliance_section(appliance_section, json_appliance)
  json_appliance_section = json_appliance[appliance_section]
  for json_communication in json_appliance_section:
    check_device_type(json_communication)

    if json_communication['type'] == 'serial':
      if found_serial:
        raise RuntimeError("Found duplicated serial device for same appliance section. Correct this.")
      check_serial_settings(json_communication)
      device_data_result = json_communication
      found_serial = True

  if not found_serial:
    raise RuntimeError("Cannot get serial device for a non serial appliance section")

  return device_data_result

def expect_on_serial(appliance, json_expect, json_conf):
  json_serial = get_serial_device(appliance, "communications", json_conf)
  check_json_expect(json_expect)

  serial_cmd = "socat -t0 STDIO,raw,echo=0,escape=0x03,nonblock=1 file:{},b{},cs8,parenb=0,cstopb=0,clocal=0,raw,echo=0".format(json_serial['device'], json_serial['baud'])
  serial_conn = pexpect.spawnu(serial_cmd, timeout=2, env=os.environ, codec_errors='ignore', logfile=sys.stdout)

  if "reset-prompt" in json_serial.keys():
    serial_conn.send(json_serial["reset-prompt"])
    if "reset-expect" in json_serial.keys():
      serial_conn.expect(json_serial["reset-expect"])

  json_expect_array = json_expect["expect"]
  for expect_entry in json_expect_array:
    serial_conn.expect(expect_entry['text'], float(expect_entry['timeout']))

def main():
  json_config_path = "./config.json"
  if not os.path.exists(json_config_path):
    raise RuntimeError("Selected configuration file {} not found".format(json_config_path))

  with open(json_config_path) as json_file:
    json_conf = json.load(json_file)

  parser = argparse.ArgumentParser(description='Controls the laboratory relay board and usb hubs.')
  arg_mutex = parser.add_mutually_exclusive_group(required=True)

  arg_mutex.add_argument("-p", "--power", choices = ['on', 'off'])
  parser.add_argument("-d", "--appliance", choices = json_conf.keys(), required=True)
  arg_mutex.add_argument('--get-serial-device', choices = ['communications', 'power'])
  arg_mutex.add_argument('--json-expect-on-serial')

  args = parser.parse_args()
  if args.power:
    do_power(args.appliance, args.power, json_conf)
  elif args.get_serial_device:
    result_json = get_serial_device(args.appliance, args.get_serial_device, json_conf)
    print(json.dumps(result_json, sort_keys=True, indent=2))
  elif args.json_expect_on_serial:
    json_expect_on_serial = json.loads(args.json_expect_on_serial)
    expect_on_serial(args.appliance, json_expect_on_serial, json_conf)
  else:
    raise ValueError("Impossible: Mandatory options not passed in arguments")

try:
  main()
except RuntimeError as e:
  print(e)
  exit(1)
