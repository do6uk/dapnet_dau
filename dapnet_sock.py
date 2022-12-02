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

import sys,socket,re,time
from queue import Queue
from threading import Thread

ric_blacklist = [] #[8,208,224,200,216,2504]

server_message_socket = '/tmp/dapnet_dau.s'


## do not edit below this line

MULTIMON = re.compile(r'^POCSAG1200:\sAddress:\s+(\d+)\s+Function:\s+(\d)\s+(Alpha|Numeric):\s+(.+)')

message_queue = Queue()
running = True

def clean_message(msg):
	remove = ['DEL','NUL','DLE','SOH','DC','STX','ETX','EOT','ENQ','NAK','ACK','SYN','BEL','ETB','BS','CAN','HT','EM','LF','SUB','VT','ESC','FF','FS','CR','GS','SO','RS','SI','US']
	for char in remove:
		msg = msg.replace('<{}>'.format(char),'')
	
	return msg

def handle_queue():
	global running, message_queue
	
	sock_connect = False
	while running:
		if not message_queue.empty():
			unix_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
			try:
				unix_socket.connect(server_message_socket)
				print('[SOCK]','connected')
				sock_connect = True
			except ConnectionRefusedError:
				print('[SOCK]','not connected - retry ...')
				time.sleep(3)
				sock_connect = False
				continue
			
			while not message_queue.empty() and sock_connect:
				message = message_queue.get()
				print('[SOCK]','MSG',message)
				try:
					unix_socket.sendall(message.encode('utf-8'))
					print('[SOCK]','MSG send')
				except BrokenPipeError:
					try:
						sock_connect = False
						unix_socket.connect(server_message_socket)
						unix_socket.sendall(message.encode('utf-8'))
						print('[SOCK]','MSG send retry')
					except:
						sock_connect = False
						break
				
				try:
					data = unix_socket.recv(1024).decode('utf-8')
					if data[0] == '+':
						print('[SOCK]','MSG ACK')
					else:
						print('[SOCK]','received invalid response',data.rstrip())
				except ConnectionResetError:
					print('[SOCK]','connection reset - retry ...')
					try:
						unix_socket.connect(server_message_socket)
						unix_socket.sendall(message.encode('utf-8'))
					except ConnectionRefusedError:
						sock_connect = False
						break
					except:
						sock_connect = False
						break
				
				time.sleep(0.1)
				
			sock_connect = False
			unix_socket.close()
			print('[SOCK]','closed')

		time.sleep(0.1)


# create que_handler
print('[dau_receiver]','init message handler ...')
que_handler = Thread(target=handle_queue)
que_handler.start()

try:
	print('[dau_receiver]','init main loop ...')
	while running:
		for line in sys.stdin:
			line_data = line.rstrip()
			print('[STDIN]','received data',line_data)
			
			# parse data
			match_data = MULTIMON.match(line_data)
			if match_data:
				m_speed = 1
				m_ric = int(match_data[1])
				m_function = int(match_data[2])
				m_type = match_data[3]
				message = clean_message(match_data[4])
				print('[STDIN]','MSG:',m_ric,m_function,m_type,message)
				
				if m_type.lower() == 'alpha':
					m_type = 6
				elif m_type.lower() == 'numeric':
					m_type = 5
				else:
					m_type = 0
					
				if not m_ric in ric_blacklist:
					data = '{:1}:{:1}:{}:{:1}:{}'.format(m_type,m_speed,m_ric,m_function,message)
					message_queue.put(data)
				else:
					print('[STDIN]','message dropped - address blacklisted',m_ric)
			else:
				print('[STDIN]','received invalid message',line_data)
				pass

except KeyboardInterrupt:
	print('[dau_receiver]','user interrupt CTRL-C ... shutdown')
	running = False
	
	que_handler.join()
