#!/usr/bin/env python3

# copyright (c) 2022 by Rainer Fiedler DO6UK
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.

import time,os,sys,socket,re,datetime,signal
from queue import Queue
from threading import Thread

tcp_address = "127.0.0.1"
tcp_port = 43434

client_slots = '2389D'

client_key = '01234'		#actually ignored
client_callsign = 'DE0ABC'	#actually ignored

server_message_socket = '/tmp/dapnet_dau.s'
use_message_socket = True

server_message_pipe = './dapnet_dau.fifo'
use_message_pipe = False

core_ping = 30	# seconds to check client-conn is still working

debug = False


## do not edit below this line

LOGIN_PATTERN = re.compile(r'^\[(.+)\s(v.+)\s(\w{2}\d\w{2,3})\s(.+)]')
TIME_PATTERN = re.compile(r'^2\:(.{4}):(.{4})')
MSG_PATTERN = re.compile(r'^(\d):(\d):(\d+):(\d):(.+)')
MSG_ACK_PATTERN = re.compile(r'^#(..)\s([\+])')

send_time_utc = True
send_time_local = True

running = True
client_online = False

def time_skyper ():
	now = datetime.datetime.utcnow()
	time_string = now.strftime("%H%M%S %d%m%y")
	# '5:1:9C8:0:%s'%time_string
	return time_string

def time_swissphone (localtime = False):
	if localtime:
		now = datetime.datetime.now()
	else:
		now = datetime.datetime.utcnow()
	time_string = now.strftime("%H%M%d%m%y")
	# '6:1:287E0:3:XTIME=%sXTIME=%s'%(time_string,time_string)
	return 'XTIME=%sXTIME=%s'%(time_string,time_string)

def time_alphapoc(localtime = False):
	if localtime:
		now = datetime.datetime.now()
	else:
		now = datetime.datetime.utcnow()
	time_string = now.strftime("%Y%m%d%H%M%S")
	# '6:1:287EA:3:YYYYMMDDHHMMSS%s'%time_string
	return 'YYYYMMDDHHMMSS%s'%time_string

def make_message(m_type, m_speed, m_ric, m_function, message):
	global last_msg, client_online, debug
	
	if client_online:
		if hex(last_msg) == 0xFF:
			last_msg = 0
		else:
			last_msg += 1
	else:
		last_msg = 0
	
	return '#{:02X} {:1}:{}:{:x}:{:1}:{}'.format(last_msg,m_type,m_speed,m_ric,m_function,message)

def send_data(data, wait_response = True, silent = False):
	global client_conn, client_online, debug
	
	if client_online:
		if not silent: print('[CLIENT]','MSG_SEND', data)
		data += '\r\n'
		try:
			client_conn.sendall(data.encode("utf-8"))
		except BrokenPipeError:
			client_online = False
			return False
	
		if wait_response:
			# wait for response
			time.sleep(0.1)
			client_conn.settimeout(2)
			rec_data = client_conn.recv(1024).decode('utf-8')
			client_conn.settimeout(None)
			if rec_data:
				msg_ack = MSG_ACK_PATTERN.match(rec_data)
				if msg_ack:
					if not silent: print('[CLIENT]','MSG_ACK',msg_ack[1])
					return msg_ack[1]
				elif rec_data.rstrip() == '+':
					if not silent: print('[CLIENT]','DATA_ACK')
					return True
				else:
					if not silent: print('[CLIENT]','received invalid response',rec_data)
					return rec_data
			else:
				print('[CLIENT]','not answered - message dropped')
				client_online = False
				return False
		else:
			return True
	else:
		print('[CLIENT]','not connected - message dropped')
		client_online = False
		return False

def send_queue():
	global running, client_conn, client_online, msg_queue, debug
	
	if debug: print('[QUEUE]','handler running')
	
	while running and client_online:
		if not msg_queue.empty():
			if debug: print('[QUEUE]','message waiting')
			while client_online and not msg_queue.empty():
				data = msg_queue.get()
				if debug: print('[QUEUE]','message processing',data)
				
				if data[0] == '#':
					m_type = 'MSG'
				else:
					m_type = 'DATA'
				
				if m_type == 'MSG': print('[CLIENT]','{}_SEND'.format(m_type), data)
				data += '\r\n'
				try:
					client_conn.sendall(data.encode("utf-8"))
				except BrokenPipeError:
					client_online = False
					break
			
				# wait for response
				time.sleep(0.1)
				client_conn.settimeout(2)
				rec_data = client_conn.recv(1024).decode('utf-8')
				client_conn.settimeout(None)

				is_ack = False
				if rec_data:
					if m_type == 'MSG':
						msg_ack = MSG_ACK_PATTERN.match(rec_data)
						if msg_ack: is_ack = True
					elif m_type == 'DATA':
						if rec_data.rstrip() == '+': is_ack = True
					
					if is_ack:
						if m_type == 'MSG': print('[CLIENT]','{}_ACK'.format(m_type))
					else:
						print('[CLIENT]','{}_NAK : invalid response'.format(m_type),rec_data)
					
					continue
				else:
					print('[CLIENT]','not answered - {} dropped'.format(m_type))
					client_online = False
					break

				time.sleep(0.1)

			if not client_online:
				print('[QUEUE]','client gone offline')
			
			if client_online and debug: print('[QUEUE]','no data')
		
		time.sleep(0.1)
	
	if debug: print('[QUEUE]','handler stopped')
	return False

def read_pipe():
	global running, server_message_pipe, msq_queue, debug
	
	try:
		os.mkfifo(server_message_pipe)
	except OSError as e:
		print('[PIPE]',server_message_pipe,'ERROR:',e.errno)
	
	while running:
		with open(server_message_pipe) as fifo:
			while running:
				data = fifo.readline()
				if len(data) == 0:
					print('[PIPE]','closed')
					break
				if debug: print('[PIPE]','DATA:',data)
				
				if data:
					msg_data = MSG_PATTERN.match(data)
					if msg_data:
						m_type = int(msg_data[1])
						m_speed = int(msg_data[2])
						m_ric = int(msg_data[3])
						m_function = int(msg_data[4])
						message = msg_data[5]
						print('[PIPE]','Message received:',m_type,m_speed,m_ric,m_function,message)
						#send_data(make_message(m_type,m_speed,m_ric,m_function,message))
						msg_queue.put(make_message(m_type,m_speed,m_ric,m_function,message))
					else:
						print('[PIPE]','received invalid message',data)
				else:
					print('pipe no data')
	return False

def read_socket():
	global running, server_message_socket, msg_queue, debug
	
	if os.path.exists(server_message_socket):
		os.remove(server_message_socket)

	unix_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	unix_socket.bind(server_message_socket)
	print('[SOCK]','ready')
	unix_socket.listen(1)
	while running:
		unix_socket_conn, addr = unix_socket.accept()
		print('[SOCK]','connect',addr)
		while running:
			try:
				unix_socket_conn.settimeout(2)
				data = unix_socket_conn.recv(1024).decode('utf-8')
				unix_socket_conn.settimeout(None)
				if data:
					print('[SOCK]','received data',data)
					msg_data = MSG_PATTERN.match(data)
					
					if msg_data:
						m_type = int(msg_data[1])
						m_speed = int(msg_data[2])
						m_ric = int(msg_data[3])
						m_function = int(msg_data[4])
						message = msg_data[5]
						print('[SOCK]','MSG:',m_type,m_speed,m_ric,m_function,message)
						
						#send_data(make_message(m_type,m_speed,m_ric,m_function,message))
						msg_queue.put(make_message(m_type,m_speed,m_ric,m_function,message))
						
					else:
						print('[SOCK]','received invalid message',data)
					
					print('[SOCK]','MSG ACK')
					unix_socket_conn.sendall('+\r\n'.encode('utf-8'))
				else:
					print('[SOCK]','close')
					unix_socket_conn.close()
			except:
				break
		
		time.sleep(0.1)
	
	unix_socket.shutdown(socket.SHUT_RDWR)
	unix_socket.close()
	return False

# init message-queue
print('[dau_core]','init message queue ...')
msg_queue = Queue()

# init fifo unix socket
if use_message_socket:
	print('[dau_core]','init SOCK ...')
	sock_reader = Thread(target=read_socket)
	sock_reader.start()

# init fifo named pipe
if use_message_pipe:
	print('[dau_core]','init PIPE ...')
	pipe_reader = Thread(target=read_pipe)
	pipe_reader.start()

# init server
print('[dau_core]','init dapnet_core ...')
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((tcp_address,tcp_port))
server.listen(1)
print('[CLIENT]','listen',tcp_address,tcp_port)
server_online = True

try:
	while server_online:
		client_conn, client_address = server.accept()
		print('[CLIENT]','connected',client_address)
		client_online = True
		
		while client_online:
			msg_queue.queue.clear()
			client_conn.settimeout(2)
			data = client_conn.recv(1024).decode('utf-8')
			client_conn.settimeout(None)
			if debug: print('[CLIENT]','received', data)
			
			# Handshake
			login = LOGIN_PATTERN.match(data)
			login_type = login.group(1)
			login_version = login.group(2)
			login_callsign = login.group(3)
			login_key = login.group(4)
			print('[CLIENT]','LOGIN:',login_type,login_version,login_callsign,login_key)
			
			# time_sync
			for x in range(0,4):
				print('[CLIENT]','TIME_SYNC',x)
				send_data('2:{:04x}'.format(x),False,True)
				
				# erwarte 2:0000:0000
				time.sleep(0.1)
				data = client_conn.recv(1024).decode('utf-8')
				for x in ['\r\n','\r']:
					data = data.replace(x,'')
				time_sync = TIME_PATTERN.match(data)
				if time_sync:
					if debug: print('[CLIENT]','TIME_SYNC',x,'received',time_sync[1],time_sync[2])
				else:
					print('[CLIENT]','TIME_SYNC',x,'received invalid response',data)
			
			# ack time_sync
			print('[CLIENT]','TIME_SYNC ACK')
			send_data('3:+0000',True,True)
			
			# send slots
			print('[CLIENT]','SET_TIMESLOTS',client_slots)
			send_data('4:'+client_slots,True,True)
			
			# main-queue
			print('[dau_core]','init client loop')

			core_timer = 0
			last_msg = 0
			last_minute = datetime.datetime.now().minute
			last_beacon = 0
			core_running = True

			print('[CLIENT]','BEACON',login_callsign)
			#send_data(make_message(6,1,8,3,login_callsign))
			msg_queue.put(make_message(6,1,8,3,login_callsign))
			
			if client_online:
				queue_handle = Thread(target=send_queue)
				queue_handle.start()
			
			while core_running and client_online:
				core_timer += 1
				if core_timer == (core_ping*2):	#core runs 0.5 secs > *2
					msg_queue.put('3:+0000')
					core_timer = 0

				minute = datetime.datetime.now().minute

				# send time-messages
				if minute != last_minute:
					
					last_minute = minute
				
					if (last_minute % 2) == 0 and send_time_utc:
						#gerade minute = UTC
						print('[CLIENT]','SKYPER_TIME')
						#send_data(make_message(5,1,2504,0,time_skyper()))
						msg_queue.put(make_message(5,1,2504,0,time_skyper()))
						print('[CLIENT]','SWISSPHONE_TIME')
						#send_data(make_message(6,1,208,3,time_swissphone()))
						msg_queue.put(make_message(6,1,208,3,time_swissphone()))
						print('[CLIENT]','ALPHAPOC_TIME')
						#send_data(make_message(6,1,224,3,time_alphapoc()))
						msg_queue.put(make_message(6,1,224,3,time_alphapoc()))
					elif send_time_local:
						#ungerade minute = Lokalzeiten
						print('[CLIENT]','SWISSPHONE_LOCALTIME')
						#send_data(make_message(6,1,200,3,time_swissphone(True)))
						msg_queue.put(make_message(6,1,200,3,time_swissphone(True)))
						print('[CLIENT]','ALPHAPOC_LOCALTIME')
						#send_data(make_message(6,1,216,3,time_alphapoc(True)))
						msg_queue.put(make_message(6,1,216,3,time_alphapoc(True)))
				
				#send transmitter beacon
				if last_beacon + 10 == minute:
					last_beacon = minute
					print('[CLIENT]','BEACON',login_callsign)
					#send_data(make_message(6,1,8,3,login_callsign))
					msg_queue.put(make_message(6,1,8,3,login_callsign))
				
				time.sleep(0.5)
			
			if not client_online:
				print('[CLIENT]','disconnected',client_address)

except KeyboardInterrupt:
	print('[dau_core]','user interrupt CTRL-C ... shutdown')
	running = False
	core_running = False
	client_online = False
	server_online = False
	
	print('[dau_core]','closing server ...')
	try:
		client_conn.close()
	except:
		pass
	server.shutdown(socket.SHUT_RDWR)
	server.close()

	print('[dau_core]','waiting for QUEUE ...')
	msg_queue.queue.clear()
	try:
		queue_handle.join(3)
	except:
		pass
	
	if use_message_socket:
		print('[dau_core]','waiting for SOCK ...')
		sock_reader.join(3)
		print('[dau_core]','SOCK closed')
	if use_message_pipe:
		print('[dau_core]','waiting for PIPE ...')
		pipe_reader.join(3)
		print('[dau_core]','PIPE closed')

	time.sleep(2)
	os.kill(os.getpid(), signal.SIGTERM)