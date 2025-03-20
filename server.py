#SOURCES USED
#https://martinxpn.medium.com/synchronizing-threads-in-python-with-semaphores-70-100-days-of-python-d6e4da203f3c
#https://docs.python.org/3/library/sqlite3.html
#https://pypi.org/project/bcrypt/
#https://flet.dev/docs/tutorials/python-chat/
#https://www.101computing.net/xor-encryption-algorithm/
#xOR encryption also studied in Secure Cyber Systems Module
#https://stackoverflow.com/questions/190010/daemon-threads-explanation
#https://stackoverflow.com/questions/393554/python-sqlite3-and-concurrency
#https://stackoverflow.com/questions/48924572/what-is-a-blocking-semaphore-in-java
#https://docs.python.org/3/library/threading.html
#https://docs.python.org/3/library/tk.html
#https://www.youtube.com/watch?v=A_Z1lgZLSNc
#https://stackoverflow.com/questions/76582258/send-bytes-in-json-format-to-the-server-in-socket-programming-python
#https://docs.python.org/3/library/os.html
#https://stackoverflow.com/questions/54598940/socket-chat-room-python-3-7
#https://www.geeksforgeeks.org/multithreading-python-set-1/


import socket
import threading
import time
import os
import json
import uuid
import datetime
import signal
import os.path
import bcrypt
import sqlite3

class LUConnectServer:
    def __init__(self, host, port, max_connections=3):
        self.host = host
        self.port = port
        self.max_connections = max_connections
        self.connection_semaphore = threading.Semaphore(max_connections)
        self.waiting_queue = []  # wait list dictionary
        self.active_clients = {}  # active client dictionary
        # initialize database
        self.db_connection = self.initialize_db()

    def initialize_db(self):
        # connect to db
        conn = sqlite3.connect("LU_Connect.db", check_same_thread=False)
        cursor = conn.cursor()
        # create user table if it doesn't exist
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        # create message table for previous messages
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS chatroom_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL,
                content BLOB NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        # create file table for transferred files
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS shared_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_data BLOB NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        conn.commit()
        return conn

    def start(self):
        # start server
        serverSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # bind to host and port
        serverSocket.bind((self.host, self.port))
        serverSocket.listen(100)
        print("Server active.")  # debug statement to make sure server is running
        # set up shutdown handler
        signal.signal(signal.SIGINT, self.shutdown_server)
        # start waiting queue thread
        waiting_queue_thread = threading.Thread(
            target=self.manage_waitqueue, daemon=True
        )
        waiting_queue_thread.start()
        # handle new connection
        try:
            while True:
                client_socket, client_address = serverSocket.accept()
                print(f"Connection request from {client_address}")

                # handle client connection in new thread
                connection_thread = threading.Thread(
                    target=self.acceptconn,
                    args=(client_socket, client_address),
                    daemon=True,
                )
                connection_thread.start()
        finally:
            serverSocket.close()
            self.db_connection.close()

    def shutdown_server(self, signum, frame):
        # shutdown function
        print("\nShutting down server...")
        # notify clients
        for username, client in self.active_clients.items():
            try:
                shutdown_msg = {
                    "type": "system",
                    "content": "Server is shutting down. Please come back later.",
                    "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                client.send_message(shutdown_msg)
                client.client_socket.close()
            except:
                pass
        # close connection to database
        if self.db_connection:
            self.db_connection.close()

    def acceptconn(self, client_socket, address):
        # accept connection and process data
        # print(f"Processing connection from {address}") DEBUG STATEMENT
        # acquire semaphore
        if self.connection_semaphore.acquire(blocking=False):
            print(f"Client {address} connected - slot available")
            # handle client
            self.handleclient(client_socket, address)
        else:
            # add to wait queue if needed
            wait_entry = {
                "socket": client_socket,
                "address": address,
                "timestamp": time.time(),
                "position": len(self.waiting_queue) + 1,
            }
            self.waiting_queue.append(wait_entry)
            print(
                f"Client {address} added to waiting queue. Position: {len(self.waiting_queue)}"
            )
            # notify client of position
            wait_msg = {
                "type": "system",
                "content": f"You are in position {len(self.waiting_queue)} in the waiting queue.",
                "estimated_wait": f"{len(self.waiting_queue) * 5} minutes",  # Estimate 5 minutes per client
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            try:
                client_socket.send(json.dumps(wait_msg).encode())
            except:
                print(f"Failed to send wait message to {address}")

    def handleclient(self, client_socket, address):
        # print(f"Handling client connection from {address}") DEBUG STATEMENT
        # handle client connection
        client_handler = ClientHandler(client_socket, address, self)
        try:
            # authenticate client
            if not client_handler.authenticate():
                print(f"Authentication failed for client {address}")
                auth_failed_msg = {
                    "type": "system",
                    "content": "Authentication failed. Disconnecting.",
                    "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                client_socket.send(json.dumps(auth_failed_msg).encode())
                client_socket.close()
                self.connection_semaphore.release()
                return
            self.active_clients[client_handler.username] = client_handler
            # print(f"Client {client_handler.username} authenticated and added to active clients") DEBUG STATEMENT

            # broadcast user joining
            self.broadcast_message(
                {
                    "type": "system",
                    "content": f"{client_handler.username} has joined the chat",
                    "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
                None,
            )  # None means don't exclude any client

            # send welcome message to new client
            welcome_msg = {
                "type": "system",
                "content": f"Welcome to LU-Connect chatroom, {client_handler.username}!",
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            client_handler.send_message(welcome_msg)
            # send chat history to new client
            self.send_chat_history(client_handler)
            # send active user list
            self.broadcast_userstatus()
            # start message receiving thread
            receive_thread = threading.Thread(
                target=client_handler.receive_chat, daemon=True
            )
            receive_thread.start()
            # wait for receiving thread to finish
            # print(f"Waiting for message reception thread to finish for {address}") DEBUG STATEMENT
            receive_thread.join()
        # exeception handling
        except Exception as e:
            print(f"Error handling client {address}: {e}")
        finally:
            if (
                hasattr(client_handler, "username")
                and client_handler.username in self.active_clients
            ):
                # broadcast user leaving
                self.broadcast_message(
                    {
                        "type": "system",
                        "content": f"{client_handler.username} has left the chat",
                        "timestamp": datetime.datetime.now().strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    },
                    client_handler.username,
                )

                del self.active_clients[client_handler.username]
            client_socket.close()
            self.connection_semaphore.release()
            print(
                f"Client {address} disconnected - connection slot released"
            )  # DEBUG STATEMENT
            # update active users
            self.broadcast_userstatus()
            # check waiting queue
            self.check_waitqueue()

    def broadcast_userstatus(self):
        # send active users to all clients
        active_usernames = list(self.active_clients.keys())
        status_update = {
            "type": "user_list",
            "users": active_usernames,
            "count": len(active_usernames),
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        self.broadcast_message(status_update, None)
        print(f"Active users broadcast: {active_usernames}")

    def broadcast_message(self, message, exclude_username=None):
        # send message to all client except excluded
        for username, client in self.active_clients.items():
            if (
                username != exclude_username
            ):  # Don't send to excluded client (typically the sender)
                try:
                    client.send_message(message)
                # exception handling
                except Exception as e:
                    print(f"Error broadcasting to {username}: {e}")

    def send_chat_history(self, client_handler, limit=50):
        # send chat history
        try:
            cursor = self.db_connection.cursor()
            cursor.execute(
                "SELECT sender, content, timestamp FROM chatroom_messages ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            history_messages = cursor.fetchall()
            if history_messages:
                history_intro = {
                    "type": "system",
                    "content": f"Showing last {len(history_messages)} messages",
                    "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                client_handler.send_message(history_intro)
                # send in chronological order
                for sender, content, timestamp in reversed(history_messages):
                    decrypted_content = self.decrypt_data(content)
                    history_message = {
                        "type": "chat",
                        "sender": sender,
                        "content": decrypted_content.decode("utf-8"),
                        "timestamp": timestamp,
                        "is_history": True,
                    }
                    client_handler.send_message(history_message)
        except Exception as e:
            print(f"Error sending chat history: {e}")

    def manage_waitqueue(self):
        # manage waiting queue and the clients
        print("Waiting queue manager started")
        while True:
            time.sleep(5)
            if self.waiting_queue:
                # update wait times
                current_time = time.time()
                for i, client in enumerate(self.waiting_queue):
                    wait_time = current_time - client["timestamp"]
                    position = i + 1
                    client["position"] = position
                    # update estimate wait time
                    est_wait_minutes = position * 5  # Estimate of 5 mins per client
                    update_msg = {
                        "type": "system",
                        "content": f"You are in position {position} in the waiting queue.",
                        "estimated_wait": f"{est_wait_minutes} minutes",
                        "elapsed_wait": f"{int(wait_time // 60)} minutes",
                        "timestamp": datetime.datetime.now().strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    }
                    try:
                        client["socket"].send(json.dumps(update_msg).encode())
                    # exception handling in case of disconnection
                    except:
                        pass
                # remove disconnected clients
                self.waiting_queue = [
                    client
                    for client in self.waiting_queue
                    if client["socket"].fileno() != -1
                ]
                print(f"Clients in waiting queue: {len(self.waiting_queue)}")

    def check_waitqueue(self):
        # check wait queue
        if self.waiting_queue:
            # acquire semaphore
            if self.connection_semaphore.acquire(blocking=False):
                # get next client
                next_client = self.waiting_queue.pop(0)
                print(
                    f"Moving client {next_client['address']} from waiting queue to active connection"
                )
                # notify client that connecting
                connect_msg = {
                    "type": "system",
                    "content": "A slot is now available. Connecting you to the server...",
                    "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                try:
                    next_client["socket"].send(json.dumps(connect_msg).encode())
                # exception handling
                except:
                    # if failed, release semaphore try new client
                    self.connection_semaphore.release()
                    self.check_waitqueue()
                    return
                # handle client
                threading.Thread(
                    target=self.handleclient,
                    args=(next_client["socket"], next_client["address"]),
                    daemon=True,
                ).start()
                # update waitlist positions
                for i, client in enumerate(self.waiting_queue):
                    position = i + 1
                    client["position"] = position
                    update_msg = {
                        "type": "system",
                        "content": f"You moved up! You are now in position {position} in the waiting queue.",
                        "estimated_wait": f"{position * 5} minutes",
                        "timestamp": datetime.datetime.now().strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    }
                    try:
                        client["socket"].send(json.dumps(update_msg).encode())
                    # exception handling in case of disconnection
                    except:
                        pass
            else:
                # release semaphore
                self.connection_semaphore.release()

    def encrypt_data(self, data):
        # encrypt data
        if isinstance(data, str):
            data = data.encode("utf-8")
        # xOR encryption with key
        key = b"LUConnectSecretKey"
        encrypted = bytearray(len(data))
        for i in range(len(data)):
            encrypted[i] = data[i] ^ key[i % len(key)]
        return encrypted

    def decrypt_data(self, encrypted_data):
        # decrypt data
        # xOR decryption with same key
        key = b"LUConnectSecretKey"
        decrypted = bytearray(len(encrypted_data))
        for i in range(len(encrypted_data)):
            decrypted[i] = encrypted_data[i] ^ key[i % len(key)]
        return decrypted

    def validate_filetype(self, filename):
        # validate file type to only allow specific file types
        allowed_types = [".docx", ".pdf", ".jpeg", ".jpg"]
        file_ext = os.path.splitext(filename)[1].lower()
        if file_ext in allowed_types:
            return True
        return False

    def store_chat_message(self, sender, content):
        # store messages in database for history
        try:
            cursor = self.db_connection.cursor()
            encrypted_content = self.encrypt_data(content)
            cursor.execute(
                "INSERT INTO chatroom_messages (sender, content) VALUES (?, ?)",
                (sender, encrypted_content),
            )
            self.db_connection.commit()
            return True
        except Exception as e:
            print(f"Error storing chat message: {e}")
            return False


class ClientHandler:
    # initialize everything necessary
    def __init__(self, client_socket, address, server):
        self.client_socket = client_socket
        self.address = address
        self.server = server
        self.username = None
        self.authenticated = False
        self.notification_muted = False

    def receive_authmsg(self):
        # handle authentication messages
        try:
            # receive 4 byte length prefix
            length_bytes = self.client_socket.recv(4)
            if not length_bytes:
                return None
            # convert prefix to integer
            message_length = int.from_bytes(length_bytes, byteorder="big")
            # receive message data
            message_data = b""
            while len(message_data) < message_length:
                chunk = self.client_socket.recv(
                    min(4096, message_length - len(message_data))
                )
                if not chunk:
                    return None
                message_data += chunk
            # parse and return message
            return json.loads(message_data.decode("utf-8"))
        # exception handling
        except Exception as e:
            print(f"Error receiving message: {e}")
            return None

    def authenticate(self):
        try:
            # send auth request to client
            auth_request = {
                "type": "auth_request",
                "message": "Please login or register",
            }
            self.send_message(auth_request)
            print(f"Sent auth request to client {self.address}")  # Debug
            # wait for response
            auth_data = self.receive_authmsg()
            if not auth_data:
                print(f"No auth data received from {self.address}")
                return False
            print(f"Received auth data: {auth_data}")  # Debug
            # check if login or registration
            auth_handler = AuthenticationHandler(self.server.db_connection)
            if auth_data["action"] == "register":
                # registration
                result = auth_handler.register_user(
                    auth_data["username"], auth_data["password"]
                )
                if result:
                    self.username = auth_data["username"]
                    self.authenticated = True
                    print(f"User {self.username} registered successfully")  # Debug
                    # send auth success message
                    self.send_message(
                        {"type": "auth_success", "username": self.username}
                    )
                    return True
                else:
                    print(f"Registration failed for {auth_data['username']}")  # Debug
                    return False
            elif auth_data["action"] == "login":
                # login
                result = auth_handler.authenticate_user(
                    auth_data["username"], auth_data["password"]
                )
                if result:
                    self.username = auth_data["username"]
                    self.authenticated = True
                    print(f"User {self.username} logged in successfully")  # Debug
                    # send auth success message
                    self.send_message(
                        {"type": "auth_success", "username": self.username}
                    )
                    return True
                else:
                    print(f"Login failed for {auth_data['username']}")  # Debug
                    return False
            else:
                print("Invalid authentication action")  # Debug
                return False
        # exception handling
        except Exception as e:
            print(f"Authentication error: {e}")  # Debug
            return False

    def send_message(self, message_dict):
        # sending message with length prefix
        try:
            message_json = json.dumps(message_dict)
            message_bytes = message_json.encode("utf-8")
            # send length as 4 byte integer, followed by message
            length_prefix = len(message_bytes).to_bytes(4, byteorder="big")
            self.client_socket.sendall(length_prefix + message_bytes)
        # exception handling
        except Exception as e:
            print(f"Error sending message to {self.username}: {e}")

    def receive_chat(self):
        # handle chat messages
        # receiving messages with length prefix
        while True:
            try:
                # receive 4 byte prefix
                length_bytes = self.client_socket.recv(4)
                if not length_bytes:
                    print(f"Connection closed for {self.username}")
                    break
                # convert length to integer
                message_length = int.from_bytes(length_bytes, byteorder="big")
                # receive message data
                message_data = b""
                while len(message_data) < message_length:
                    chunk = self.client_socket.recv(
                        min(4096, message_length - len(message_data))
                    )
                    if not chunk:
                        print(
                            f"Connection closed during message reception for {self.username}"
                        )
                        return
                    message_data += chunk
                # parse and process message
                message = json.loads(message_data.decode("utf-8"))
                print(f"Received message from {self.username}: {message}")

                # process message type
                if message["type"] == "chat":
                    self.process_chat_message(message)
                elif message["type"] == "file_transfer_init":
                    self.handle_file_transfer_init(message)
                elif message["type"] == "file_transfer_data":
                    self.handle_file_transfer_data(message)
                elif message["type"] == "command":
                    self.process_command(message)
            # exception handling
            except Exception as e:
                print(f"Error in receive_msgs for {self.username}: {e}")
                break

    def process_chat_message(self, message):
        # process incoming chat message
        # add timestamp
        if "timestamp" not in message:
            message["timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # add sender info
        message["sender"] = self.username
        # store message in database
        self.server.store_chat_message(self.username, message["content"])
        # send to all clients
        self.server.broadcast_message(
            message, self.username
        )  # Don't send back to sender
        # confirm status to sender
        status_msg = {
            "type": "message_status",
            "message_id": message.get("id", str(uuid.uuid4())),
            "status": "delivered",
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.send_message(status_msg)

    def handle_file_transfer_init(self, message):
        # file transfer initialization
        # check if allowed file type
        filename = message["filename"]
        if not self.server.validate_filetype(filename):
            # send error if not
            error_msg = {
                "type": "error",
                "content": f"File type not allowed. Only .docx, .pdf, .jpeg, .jpg files are accepted.",
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self.send_message(error_msg)
            return
        # ff allowed, prepare for transfer
        ack_msg = {
            "type": "file_transfer_ack",
            "file_id": str(uuid.uuid4()),
            "filename": filename,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.send_message(ack_msg)

    def handle_file_transfer_data(self, message):
        # handle transfer data and extract file info
        file_id = message["file_id"]
        filename = message["filename"]
        file_data = message["data"].encode("latin-1")  # Convert back to bytes
        # encrypt file data
        encrypted_data = self.server.encrypt_data(file_data)
        # store file in database
        cursor = self.server.db_connection.cursor()
        cursor.execute(
            "INSERT INTO shared_files (sender, filename, file_data) VALUES (?, ?, ?)",
            (self.username, filename, encrypted_data),
        )
        self.server.db_connection.commit()
        # get file ID
        cursor.execute("SELECT last_insert_rowid()")
        db_file_id = cursor.fetchone()[0]
        # notify all clients about file
        file_notification = {
            "type": "file_notification",
            "sender": self.username,
            "filename": filename,
            "file_id": db_file_id,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.server.broadcast_message(
            file_notification, None
        )  # Notify everyone including sender
        # send system message to chat about file
        file_chat_msg = {
            "type": "system",
            "content": f"{self.username} shared a file: {filename}",
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.server.broadcast_message(file_chat_msg, None)
        # confirm successful transfer
        confirm_msg = {
            "type": "file_transfer_complete",
            "file_id": file_id,
            "db_file_id": db_file_id,
            "filename": filename,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.send_message(confirm_msg)

    def process_command(self, message):
        # handle commands
        command = message["command"]
        # mute notifications
        if command == "mute_notifications":
            self.notification_muted = True
            response = {
                "type": "command_response",
                "command": command,
                "status": "success",
                "message": "Notifications have been muted",
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        # unmute notifications
        elif command == "unmute_notifications":
            self.notification_muted = False
            response = {
                "type": "command_response",
                "command": command,
                "status": "success",
                "message": "Notifications have been unmuted",
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        elif command == "download_file":
            # handle file download requests
            file_id = message["file_id"]
            self.handle_file_download(file_id)
            return
        elif command == "logout":
            # handle logout
            response = {
                "type": "command_response",
                "command": command,
                "status": "success",
                "message": "Logging out...",
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self.send_message(response)
            # close connection
            self.client_socket.close()
            return
        elif command == "get_user_list":
            # send current users
            self.server.broadcast_userstatus()
            return
        else:
            response = {
                "type": "command_response",
                "command": command,
                "status": "error",
                "message": "Unknown command",
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

        self.send_message(response)

    def handle_file_download(self, file_id):
        # handle file download from shared files
        cursor = self.server.db_connection.cursor()
        cursor.execute(
            "SELECT id, sender, filename, file_data FROM shared_files WHERE id = ?",
            (file_id,),
        )
        file_record = cursor.fetchone()
        if file_record:
            file_id, sender, filename, encrypted_data = file_record
            # decrypt file data
            decrypted_data = self.server.decrypt_data(encrypted_data)
            # send file to client
            file_msg = {
                "type": "file_data",
                "file_id": file_id,
                "sender": sender,
                "filename": filename,
                "data": decrypted_data.decode(
                    "latin-1"
                ),  # Convert bytes to string for JSON
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self.send_message(file_msg)
            # system message for downloader
            download_msg = {
                "type": "system",
                "content": f"Downloaded {filename} shared by {sender}",
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self.send_message(download_msg)
        else:
            error_msg = {
                "type": "error",
                "content": f"File not found",
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self.send_message(error_msg)


class AuthenticationHandler:
    # handle authentication
    def __init__(self, db_connection):
        self.db_connection = db_connection

    def register_user(self, username, password):
        try:
            # check if user exists
            cursor = self.db_connection.cursor()
            cursor.execute("SELECT username FROM users WHERE username = ?", (username,))
            if cursor.fetchone():
                return False
            # hash password
            hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
            # store user credentials
            cursor.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, hashed_password.decode("utf-8")),
            )
            self.db_connection.commit()
            return True
        except Exception as e:
            print(f"Registration error: {e}")
            return False

    def authenticate_user(self, username, password):
        # authentication
        try:
            cursor = self.db_connection.cursor()
            cursor.execute("SELECT password FROM users WHERE username = ?", (username,))
            user_record = cursor.fetchone()
            if user_record:
                stored_password = user_record[0]
                print(
                    f"Stored password hash for {username}: {stored_password}"
                )  # Debug line
                # handle password
                if isinstance(stored_password, bytes):
                    # if in bytes, use
                    return bcrypt.checkpw(password.encode("utf-8"), stored_password)
                else:
                    # if string, encode
                    return bcrypt.checkpw(
                        password.encode("utf-8"), stored_password.encode("utf-8")
                    )
            print("Username not found")  # Debug line
            return False
        # exception handling auth error
        except Exception as e:
            print(f"Authentication error: {e}")
            return False


# main code to run file
if __name__ == "__main__":
    server = LUConnectServer("localhost", 8000)
    server.start()
