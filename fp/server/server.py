#!/usr/bin/python3

import requests
import json
import threading
import signal
import sys
import socketserver
import secrets
import mysql.connector
import subprocess

login_url = "http://php-apache/login.php"
username = 'test'
database_username = "phpadmin"
database_passwd_file = f"/run/secrets/db_{database_username}_password"
local_server_addr = address = ('0.0.0.0', 9080)
db_ipaddress = 'mariadb' # subprocess.check_output('docker inspect -f \'{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}\' server_mariadb_1', shell=True)

server = None

auth_codes = {}

def cat(filename):
    f = open(filename,mode='r')
    s = f.read()
    f.close()
    return s #.strip('\n\t ')


class ServerConnectionHandler(socketserver.StreamRequestHandler):
    def handle_login(self, data):
        print("Login Attempt: ", data)

        session = requests.Session()
        reply = session.post(login_url, data=data)
        replyjson = json.loads(reply.text)

        token = None
        if 'error' not in replyjson or replyjson['error'] is None:
            token = secrets.token_hex(16)
            auth_codes[self] = { 'connection': self, 'user': replyjson, 'token': token }
            replyjson['token'] = token

            print("Login Success: ", data)

        return replyjson

    def handle_update(self, msg):
        global db_ipaddress, database_username, database_passwd_file

        db = mysql.connector.connect(
            host=db_ipaddress,
            user=database_username,
            password=cat(database_passwd_file),
            database="sense49"
        )

        cursor = db.cursor()

        sql = "UPDATE sensors SET state=%s WHERE id=%s"
        # f"UPDATE sensors SET state={msg['state']} WHERE id={msg['update_sensor_id']}"
        # print(sql)
        val = [ msg['state'], msg['update_sensor_id'] ]
        cursor.execute(sql, val)
        mydb.commit()
        print("Updated")

        sql = "SELECT * FROM sensors WHERE id=%s" # id,userid,type,name,number,state
        val = [ msg['update_sensor_id'] ]
        cursor.execute(sql, val)
        print("Selected")
        result = cursor.fetchall()[0]

        jsonreply = {}
        jsonreply['id']     = result[0]
        jsonreply['userid'] = result[1]
        jsonreply['type']   = result[2]
        jsonreply['name']   = result[3]
        jsonreply['number'] = result[4]
        jsonreply['state']  = result[5]

        return jsonreply

    def handle_device(self, msg):
        # if msg['update_sensor_id']
        jsonmsg = json.dumps(msg)
        print("Replying: %s" % jsonmsg)
        msg = str(len(jsonmsg)) + '\n' + jsonmsg
        self.wfile.write(msg.encode())

    def handle(self):
        print("Connection Received")
        while True:
            data = self.rfile.readline().strip()
            msg_len = int(data.decode())

            data = b''
            len_recv = 0
            while len_recv < msg_len:
                read_rem = msg_len - len_recv
                data += self.rfile.read(read_rem)
                len_recv = len(data)

            msg = data.decode()
            print("JSON Recived: %s" % msg)
            msgjson = json.loads(msg)
            
            reqtype = msgjson['opcode']
            replyjson = None
            if reqtype == 'login':
                replyjson = self.handle_login(msgjson)
            if reqtype == 'update':
                replyjson = self.handle_update(msgjson)
            if reqtype == 'device':
                print("Recived Device update.")
                for k in auth_codes.keys():
                    k.handle_device(msgjson)
                return

            jsonmsg = json.dumps(replyjson)
            print("Replying: %s" % jsonmsg)
            msg = str(len(jsonmsg)) + '\n' + jsonmsg
            self.wfile.write(msg.encode())


def signal_handler(sig, frame):
    server.stopJoin()
    sys.exit(0)

if __name__ == '__main__':
    #signal.signal(signal.SIGINT, signal_handler)

    # See https://stackoverflow.com/questions/16433522
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(local_server_addr, ServerConnectionHandler)
    with server:
        server.serve_forever()
        print("Server Started")
