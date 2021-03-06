#!/usr/bin/env python3

import os
import sys
import argparse
import json
import pexpect
import time

class Tee(object):
  def __init__(self, name, mode):
    self.name = name
    self.file = open(name, mode)
    self.stdout = sys.stdout
    print("Log file in {}".format(name))
  def __del__(self):
    self.file.close()
    print("Closed Log file in {}".format(self.name))
  def write(self, data):
    self.file.write(data)
    self.stdout.write(data)
  def flush(self):
    self.file.flush()

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
    print(' '.join(json_conf.keys()))
    raise RuntimeError("appliance {} not found in configuration.".format(appliance))

def check_appliance_section(appliance_section, json_appliance):
  if appliance_section  not in json_appliance.keys():
    raise RuntimeError("Cannot find {} configurations".format(appliance_section))

def check_device_type(json_appliance_section):
  if 'type' not in json_appliance_section.keys():
    raise RuntimeError("type not defined in appliance section")

def get_power_group(group_json):
  if "devices" not in group_json.keys():
    raise RuntimeError("Found a group with no devices. Please correct the type or add devices")

  return group_json["devices"]

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

  for action in json_communication['command'].keys():
    for json_action_command in json_communication['command'][action]:
      if is_invalid_command(json_action_command):
        raise RuntimeError("execute or io keys are mandatory for all actions")

      check_io(json_action_command)

def get_serial_cmd(device, baud):
  return "socat -t0 STDIO,raw,echo=0,escape=0x03,nonblock=1 " \
      "file:{},b{},cs8,parenb=0,cstopb=0,clocal=0,raw,echo=0".format(device, baud)

def do_execute(execute, logger, shell = False):
  if shell:
    execute = "bash -c '{}'".format(execute)

  return pexpect.spawnu(execute, env = os.environ, codec_errors = 'ignore', logfile = logger)

def do_expect(conn, expect = None, match_type = None, timeout = 2):
  if expect:
    try:
      if match_type == "re":
        conn.expect(expect, timeout = int(timeout))
      else:
        conn.expect_exact(expect, float(timeout))

      print("Expect success: {}".format(expect))
    except pexpect.TIMEOUT:
      raise RuntimeError("""Expect fail: {}
*************BUFFER DUMP START************
{}
*************BUFFER DUMP END**************
""".format(expect, conn.buffer))

def do_send(conn, text = None):
  if text:
    conn.send(text)

def do_host_command(action_json, log_directory, kill_after_expect = False):
  if "execute" not in action_json.keys():
    raise RuntimeError("'execute' directive required for command")

  execute = action_json["execute"]

  timestr = time.strftime("%Y%m%d-%H%M%S")
  file_suffix = os.path.basename(execute.split()[0]).replace(" ", "_")
  log_file_basename = "lab-controller-{}-{}.log".format(file_suffix, timestr)
  log_file_name = os.path.join(log_directory, log_file_basename)
  logfile = Tee(log_file_name, "w")

  exec_conn = do_execute(execute, logfile, True)
  if "io" in action_json.keys():
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


  if kill_after_expect and exec_conn.isalive():
    #we are done here and we want to leave.
    if not exec_conn.terminate(True):
      raise RuntimeError("Application blocked and could not be terminated. Error")

  if not kill_after_expect and exec_conn.wait() != 0:
    do_expect(exec_conn, pexpect.EOF)
    exec_conn.close()
    raise RuntimeError("Host Command did not execute successfully: {}. Exit status {}; Signal status: {}".format(
      execute, exec_conn.exitstatus, exec_conn.signalstatus))

  do_expect(exec_conn, pexpect.EOF)
  exec_conn.close()

def do_power_serial(action, json_power, log_directory):
  check_serial_settings(json_power)
  check_command(json_power)

  power_cmd = get_serial_cmd(json_power['device'], json_power['baud'])

  if action in json_power["command"]:
    for json_action_command in json_power['command'][action]:
      if "io" not in json_action_command.keys():
        raise RuntimeError("io section required for serial devices")

      check_io(json_action_command)

    json_action_command["execute"] = power_cmd
    do_host_command(json_action_command, log_directory, True)

def do_power_usb(action, json_power, log_directory):
  check_usb_json(json_power)

  execute = 'uhubctl -a {} -l {} -p {}'.format(action, json_power['usb-address'], json_power['usb-port'])
  io_list = []
  io_list.append({ "expect" : {"text" : 'Sent power {} request'.format(action)}})
  io_list.append({ "expect" : {"text" : 'New status for hub {}'.format(json_power['usb-address'])}})

  if action == "off":
    io_list.append({ "expect" : { "text" : '  Port {}: 0000 {}'.format(json_power['usb-port'], action)}})
  if action == "on":
    io_list.append({ "expect" : { "text" : '  Port {}: [0-9]{{4}} power'.format(json_power['usb-port']),
      "match-type" : "re"}})
  json_action_command = {"execute" : execute, "io" : io_list}
  do_host_command(json_action_command, log_directory)

def do_power_command(action, json_power, log_directory):
  check_command(json_power)

  if action in json_power["command"]:
    for json_action_command in json_power["command"][action]:
      do_host_command(json_action_command, log_directory)

def parse_power(json_communication_method, action, log_directory):
  check_device_type(json_communication_method)
  if json_communication_method['type'] == 'serial':
    do_power_serial(action, json_communication_method, log_directory)
  elif json_communication_method['type'] == 'usb':
    do_power_usb(action, json_communication_method, log_directory)
  elif json_communication_method['type'] == 'host':
    do_power_command(action, json_communication_method, log_directory)
  else:
    raise RuntimeError("type {} is not supported".format(json_communication_method['type']))

def parse_power_optional(json_communication_method, action, optional_power, log_directory):
  optional_json_data = {}
  if not optional_power:
    print("skipped option {} because no data passed about it".format(json_communication_method['id']))
  elif os.path.exists(optional_power):
    with open(optional_power) as f:
      optional_json_data = json.load(f)
  else:
    optional_json_data = json.loads(optional_power)

  for option in optional_json_data.keys():
    if option == json_communication_method['id']:
      print('found option for id: {}'.format(option))
      for option_power_method in optional_json_data[option]:
        parse_power(option_power_method, action, log_directory)

def do_power(appliance, action, json_conf, log_directory, optional_power = None,):
  appliance_section = 'power'

  check_applicance(appliance, json_conf)
  json_appliance = json_conf[appliance]
  check_appliance_section(appliance_section, json_appliance)
  json_appliance_section = json_appliance[appliance_section]

  for json_communication_method in json_appliance_section:
    if json_communication_method['type'] == 'optional':
      parse_power_optional(json_communication_method, action, optional_power, log_directory)
    elif json_communication_method['type'] == 'group':
      devices = get_power_group(json_communication_method)
      for device in devices:
        do_power(device, action, json_conf, log_directory, optional_power)
    else:
      parse_power(json_communication_method, action, log_directory)

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

  timestr = time.strftime("%Y%m%d-%H%M%S")
  log_file_name = "/tmp/lab-controller-serial-{}{}.log".format(json_serial["device"],timestr)
  with open(log_file_name, 'wb') as logfile:
    serial_conn = pexpect.spawnu(serial_cmd, timeout=2, env=os.environ, codec_errors='ignore', logfile=logfile)

    if "reset-prompt" in json_serial.keys():
      serial_conn.send(json_serial["reset-prompt"])
      if "reset-expect" in json_serial.keys():
        serial_conn.expect(json_serial["reset-expect"])

    json_expect_array = json_expect["expect"]
    for expect_entry in json_expect_array:
      serial_conn.expect(expect_entry['text'], float(expect_entry['timeout']))

def main():
  json_config_path = "./config.json"

  parser = argparse.ArgumentParser(description='Controls the laboratory relay board and usb hubs.')
  arg_mutex = parser.add_mutually_exclusive_group(required=True)

  arg_mutex.add_argument("-p", "--power", choices = ['on', 'off'])
  parser.add_argument("-c", "--config", help = "Option for the path of an external configuration .json file")
  parser.add_argument("-d", "--appliance", required=True)
  parser.add_argument("--optional-power", help = "a json file with options or serialized json")
  parser.add_argument("-l", "--log-directory", default = "/tmp", help = "The directory where logs should be stored. Default is /tmp")
  arg_mutex.add_argument('--get-serial-device', choices = ['communications', 'power'])
  arg_mutex.add_argument('--json-expect-on-serial')

  args = parser.parse_args()

  if args.config:
    json_config_path = args.config

  if not os.path.exists(json_config_path):
    raise RuntimeError("Selected configuration file {} not found".format(json_config_path))

  with open(json_config_path) as json_file:
    json_conf = json.load(json_file)

  if args.power:
    do_power(args.appliance, args.power, json_conf, args.log_directory, args.optional_power)
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
