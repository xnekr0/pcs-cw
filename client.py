import socket
import threading
import json
import os
import datetime
import tkinter as tk
from tkinter import scrolledtext, filedialog, messagebox


class LUConnectClient:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.username = None
        self.socket = None
        self.connected = False
        self.message_callback = None
        self.status_callback = None
        self.receiver_thread = None
        self.file_transfers = {}

    def connect(self):
        #connect to server
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            self.connected = True
        #start receive thread
            self.receiver_thread = threading.Thread(target=self.receive_messages, daemon=True)
            self.receiver_thread.start()
            return True
        #exception handling for connection error
        except Exception as e:
            print(f"Connection error: {e}")
            return False

    def authenticate(self, username, password, is_register=False):
        #authenticate user on server
        action = "register" if is_register else "login"
        #receive user data and login/register action
        auth_data = {
            "action": action,
            "username": username,
            "password": password
        }
        self.send_message(auth_data)
        #authentication handled in receive_messages

    def send_message(self, message_dict):
        #send message to server with length_prefix
        try:
            message_json = json.dumps(message_dict)
            message_bytes = message_json.encode('utf-8')
            # Send length as 4-byte integer, followed by the message
            length_prefix = len(message_bytes).to_bytes(4, byteorder='big')
            self.socket.sendall(length_prefix + message_bytes)
        #exception couldnt handle message
        except Exception as e:
            print(f"Error sending message: {e}")
            self.connected = False

    def send_chat_message(self, content):
        #send chat message to all active users
        msg = {
            "type": "chat",
            "content": content,
            "id": datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        }
        self.send_message(msg)

    def receive_messages(self):
        #receive and process messages - loop
        while self.connected:
            try:
                #receive 4 byte prefix
                length_bytes = b''
                while len(length_bytes) < 4:
                    chunk = self.socket.recv(4 - len(length_bytes))
                    if not chunk:
                        print("Connection closed while receiving length prefix")
                        self.connected = False
                        break
                    length_bytes += chunk
                if not self.connected:
                    break
                #convert prefix to integer
                message_length = int.from_bytes(length_bytes, byteorder='big')
                #receive message data
                message_data = b''
                while len(message_data) < message_length:
                    chunk = self.socket.recv(min(4096, message_length - len(message_data)))
                    if not chunk:
                        print("Connection closed during message receiving.")
                        self.connected = False
                        break
                    message_data += chunk
                #parse message
                if message_data and len(message_data) == message_length:
                    try:
                        message = json.loads(message_data.decode('utf-8'))
                        print(f"Received message: {message}")
                        self.process_message(message)
                    except json.JSONDecodeError as e:
                        print(f"JSON decode error: {e}, Raw data: {message_data}")
            #exception handling for receiving error
            except Exception as e:
                print(f"Receiving error: {e}")
                self.connected = False
                break

        #handle disconnection
        if self.status_callback:
            self.status_callback("disconnected")

    def process_message(self, message):
        #process message based on type
        msg_type = message.get("type")

        if msg_type == "auth_request":
            #handle auth request by GUI
            if self.status_callback:
                self.status_callback("auth_requested")

        elif msg_type == "auth_success":
            #auth successful
            self.username = message.get("username")
            if self.status_callback:
                self.status_callback("authenticated", self.username)

        elif msg_type in ["chat", "system", "user_list", "file_notification", "error", "message_status"]:
            #forward these message types to UI
            if self.message_callback:
                self.message_callback(message)

        elif msg_type == "file_transfer_ack":
            #acknowledge file transfer
            file_id = message.get("file_id")
            filename = message.get("filename")
            file_path = self.file_transfers.get(filename)
            if file_path:
                self.send_file_data(file_id, filename, file_path)

        elif msg_type == "file_data":
            #receive file data
            self.handle_received_file(message)

    def send_file_init(self, file_path):
        #send file initialization
        filename = os.path.basename(file_path)
        self.file_transfers[filename] = file_path
        msg = {
            "type": "file_transfer_init",
            "filename": filename
        }
        self.send_message(msg)

    def send_file_data(self, file_id, filename, file_path):
        #send file data to server
        try:
            with open(file_path, "rb") as file:
                file_data = file.read()
            #convert binary to string for json
            data_str = file_data.decode('latin-1')
            msg = {
                "type": "file_transfer_data",
                "file_id": file_id,
                "filename": filename,
                "data": data_str
            }
            self.send_message(msg)
        #file send exception handling
        except Exception as e:
            print(f"Error sending file: {e}")

    def handle_received_file(self, message):
        #handle received file data
        filename = message.get("filename")
        file_data = message.get("data").encode('latin-1')  # Convert back to bytes
        #let GUI handle file
        if self.message_callback:
            message["file_data"] = file_data
            self.message_callback(message)

    def download_file(self, file_id):
        #request file download
        msg = {
            "type": "command",
            "command": "download_file",
            "file_id": file_id
        }
        self.send_message(msg)

    def disconnect(self):
        #disconnect from server
        if self.connected:
            try:
                #send logout command
                self.send_message({"type": "command", "command": "logout"})
                self.socket.close()
            except:
                pass
            finally:
                self.connected = False

#GUI class for client
class ClientUI:
    def __init__(self, master):
        #initialize everything necessary
        self.master = master
        self.master.title("LU Connect Client")
        self.master.geometry("800x600")
        self.client = LUConnectClient("localhost", 8000)
        self.client.message_callback = self.handle_message
        self.client.status_callback = self.handle_status
        self.setup_ui()

    def setup_ui(self):
        #set-up client window
        #main window
        self.main_frame = tk.Frame(self.master)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        #status label
        self.status_label = tk.Label(self.main_frame, text="Connecting to server...", fg="blue")
        self.status_label.pack(pady=5)
        # login window with all input lines
        self.login_frame = tk.Frame(self.main_frame)
        self.login_frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(self.login_frame, text="Username:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.username_entry = tk.Entry(self.login_frame, width=20)
        self.username_entry.grid(row=0, column=1, padx=5, pady=5)
        tk.Label(self.login_frame, text="Password:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.password_entry = tk.Entry(self.login_frame, width=20, show="*")
        self.password_entry.grid(row=1, column=1, padx=5, pady=5)
        btn_frame = tk.Frame(self.login_frame)
        btn_frame.grid(row=2, column=0, columnspan=2, pady=10)
        self.login_btn = tk.Button(btn_frame, text="Login", command=self.login, width=10)
        self.login_btn.pack(side=tk.LEFT, padx=5)
        self.register_btn = tk.Button(btn_frame, text="Register", command=self.register, width=10)
        self.register_btn.pack(side=tk.LEFT, padx=5)
        #chat window, hidden at start
        self.chat_frame = tk.Frame(self.main_frame)
        #split window into chat/user list
        paned_window = tk.PanedWindow(self.chat_frame, orient=tk.HORIZONTAL)
        paned_window.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        #user list part
        user_frame = tk.Frame(paned_window, width=150)
        tk.Label(user_frame, text="Online Users").pack(pady=5)
        self.user_list = tk.Listbox(user_frame)
        self.user_list.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        paned_window.add(user_frame)
        #chat display part
        chat_display_frame = tk.Frame(paned_window)
        paned_window.add(chat_display_frame)
        #chat display
        self.chat_display = scrolledtext.ScrolledText(chat_display_frame, state='disabled', height=20)
        self.chat_display.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.chat_display.tag_configure("system", foreground="blue")
        #message input
        self.message_frame = tk.Frame(self.chat_frame)
        self.message_frame.pack(fill=tk.X, padx=5, pady=5)
        self.message_entry = tk.Entry(self.message_frame, width=50)
        self.message_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.message_entry.bind("<Return>", self.send_message)
        self.send_btn = tk.Button(self.message_frame, text="Send", command=self.send_message)
        self.send_btn.pack(side=tk.LEFT, padx=5)
        self.file_btn = tk.Button(self.message_frame, text="Send File", command=self.send_file)
        self.file_btn.pack(side=tk.LEFT, padx=5)
        #initialize connection
        if not self.client.connect():
            self.status_label.config(text="Failed to connect to server", fg="red")
            messagebox.showerror("Connection Error", "Could not connect to the server")
            self.master.after(2000, self.master.destroy)
        else:
            self.status_label.config(text="Connected to server", fg="green")

    def login(self):
        #handle login
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()
        self.status_label.config(text="Logging in...", fg="blue")
        self.client.authenticate(username, password, is_register=False)

    def register(self):
        #handle registration
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()
        self.status_label.config(text="Registering...", fg="blue")
        self.client.authenticate(username, password, is_register=True)

    def send_message(self, event=None):
        #send chat message
        message = self.message_entry.get().strip()
        if message:
            #forward message to server
            self.client.send_chat_message(message)
            #display own messages locally
            self.chat_display.config(state='normal')
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.chat_display.insert(tk.END, f"[{timestamp}] {self.client.username}: {message}\n")
            self.chat_display.config(state='disabled')
            self.chat_display.see(tk.END)
            #clear entry field
            self.message_entry.delete(0, tk.END)

    def send_file(self):
        #send file
        file_path = filedialog.askopenfilename(
            filetypes=[
                ("Documents", "*.docx *.pdf"),
                ("Images", "*.jpg *.jpeg")
            ]
        )
        if file_path:
            self.client.send_file_init(file_path)

    def handle_message(self, message):
        #handle received messages based on type
        msg_type = message.get("type")
        if msg_type == "chat" or msg_type == "system":
            self.display_message(message)
        elif msg_type == "user_list":
            self.update_user_list(message)
        elif msg_type == "file_notification":
            self.display_file_notification(message)
        elif msg_type == "file_data":
            self.save_received_file(message)

    def update_user_list(self, message):
        #update user list in GUI
        users = message.get("users", [])
        self.user_list.delete(0, tk.END)
        for user in users:
            self.user_list.insert(tk.END, user)

    def display_message(self, message):
        #display message in chat window
        self.chat_display.config(state='normal')
        #get time stamp
        timestamp = message.get("timestamp", "")
        if message.get("type") == "system":
            content = f"[{timestamp}] SYSTEM: {message.get('content')}\n"
            self.chat_display.insert(tk.END, content, "system")
        else:
            sender = message.get("sender", "Unknown")
            content = message.get("content", "")
            self.chat_display.insert(tk.END, f"[{timestamp}] {sender}: {content}\n")
        self.chat_display.config(state='disabled')
        self.chat_display.see(tk.END)

    def display_file_notification(self, message):
        #display file notification and download button
        self.chat_display.config(state='normal')
        sender = message.get("sender", "Unknown")
        filename = message.get("filename", "file")
        file_id = message.get("file_id")
        timestamp = message.get("timestamp", "")
        #file notification
        self.chat_display.insert(tk.END, f"[{timestamp}] {sender} shared a file: {filename}\n", "system")
        #download button
        download_frame = tk.Frame(self.chat_display)
        download_btn = tk.Button(
            download_frame,
            text=f"Download {filename}",
            command=lambda fid=file_id: self.download_file(fid)
        )
        download_btn.pack(pady=2)
        self.chat_display.window_create(tk.END, window=download_frame)
        self.chat_display.insert(tk.END, "\n")
        self.chat_display.config(state='disabled')
        self.chat_display.see(tk.END)

    def download_file(self, file_id):
        #download file
        self.client.download_file(file_id)

    def save_received_file(self, message):
        #save file
        filename = message.get("filename", "downloaded_file")
        file_data = message.get("file_data")
        save_path = filedialog.asksaveasfilename(
            initialfile=filename,
            defaultextension=os.path.splitext(filename)[1]
        )
        if save_path:
            try:
                with open(save_path, "wb") as file:
                    file.write(file_data)
                messagebox.showinfo("File Downloaded", f"File saved as {save_path}")
            except Exception as e:
                messagebox.showerror("Download Error", f"Could not save file: {e}")

    def handle_status(self, status, *args):
        #handle client status
        if status == "auth_requested":
            self.status_label.config(text="Please login or register", fg="blue")
        elif status == "authenticated":
            #switch to chat window
            self.status_label.config(text=f"Logged in as {args[0]}", fg="green")
            self.login_frame.pack_forget()
            self.chat_frame.pack(fill=tk.BOTH, expand=True)
            self.master.title(f"LU Connect - {args[0]}")
        #handle disconnect
        elif status == "disconnected":
            self.status_label.config(text="Disconnected from server", fg="red")
            messagebox.showinfo("Disconnected", "You have been disconnected from the server")
            self.master.after(2000, self.master.destroy)

#main function to run client
if __name__ == "__main__":
    root = tk.Tk()
    app = ClientUI(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.client.disconnect(), root.destroy()))
    root.mainloop()