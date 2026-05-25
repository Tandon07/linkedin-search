# Azure Free Tier Deployment Guide with GitHub CI/CD
===================================================

This guide details how to host the LinkedIn Job Application Automator completely **for free** on Microsoft Azure using your **BITS Pilani Student Account**, and configure automatic push-to-deploy updates using **GitHub Actions**.

---

## Phase 1: Create Your Free Azure Virtual Machine (VM)

Azure for Students includes **750 hours of Linux B1s Burstable VM free every month** (valid for 12 months, which covers a standard year of 24/7 background usage).

### Step 1: Sign In and Configure the VM
1. Go to the [Azure Portal](https://portal.azure.com/) and sign in using your **BITS Pilani student account** (`username@pilani.bits-pilani.ac.in`).
2. Search for **Virtual machines** in the top search bar and click **Create** -> **Azure virtual machine**.
3. Fill in the following details:
   - **Subscription**: `Azure for Students`
   - **Resource group**: Click *Create new* and name it `linkedin-automator-rg`.
   - **Virtual machine name**: `linkedin-bot-vm`
   - **Region**: Select a region close to you (e.g., `Central India` or `East US`).
   - **Availability options**: `No infrastructure redundancy required`
   - **Security type**: `Standard`
   - **Image**: `Ubuntu Server 22.04 LTS - x64 Gen2` (Free services eligible).
   - **Size**: **`Standard_B2ats_v2`** (2 vCPUs, 1 GiB memory) -> **Make sure it shows "Free services eligible"**.
   
### Step 2: Configure Authentication & Networking
1. **Administrator account**:
   - **Authentication type**: `SSH public key`
   - **Username**: `azureuser`
   - **SSH key source**: `Generate new key pair`
   - **Key pair name**: `linkedin-bot-key`
2. **Inbound port rules**:
   - **Public inbound ports**: `Allow selected ports`
   - **Select inbound ports**: Check **`SSH (22)`** (Do not open any other ports for maximum security).
3. Click **Review + create** at the bottom.
4. Once validation passes, click **Create**.
5. **CRITICAL**: A prompt will pop up to download the private key. Click **Download private key and create resource** and save the `.pem` file (e.g., `linkedin-bot-key.pem`) securely on your computer.

---

## Phase 2: Connect and Provision the Server

Once your VM is ready, find its **Public IP address** on the VM Overview page.

### Step 1: SSH into your Azure VM
Open a terminal on your computer (Command Prompt, PowerShell, or Git Bash) and run:
```bash
# Secure the permission of the key file (if you are on Linux/macOS)
chmod 400 /path/to/linkedin-bot-key.pem

# SSH connect to the VM
ssh -i /path/to/linkedin-bot-key.pem azureuser@<VM-PUBLIC-IP>
```
*(Replace `<VM-PUBLIC-IP>` with your actual Azure VM Public IP and `/path/to/linkedin-bot-key.pem` with your key's path).*

### Step 2: Clone the Project
On the VM terminal, run:
```bash
# Clone your repository from GitHub
git clone https://github.com/Tandon07/linkedin-search.git linkedin

# Enter the directory
cd linkedin
```

### Step 3: Configure Environment Variables
Copy the environment template and fill in your actual private credentials:
```bash
cp .env.example .env
nano .env
```
*(Use Arrow keys to navigate, fill in your LinkedIn credentials, Groq API key, email accounts/passwords, and make sure `HEADLESS=True` is active. Press `Ctrl+O` then `Enter` to save, and `Ctrl+X` to exit).*

### Step 4: Run the Automated Provisioning Script
Run the automated script we created to install Chrome, virtual environments, system packages, and setup system service:
```bash
chmod +x setup_vm.sh
./setup_vm.sh
```

### Step 5: Start & Verify the Background Worker
Now, start the background system service which will run main.py on the schedule you configured:
```bash
# Start the service
sudo systemctl start linkedin-automator.service

# Verify the service is active and running
sudo systemctl status linkedin-automator.service

# View running logs in real-time
journalctl -u linkedin-automator.service -f -n 50
```

---

## Phase 3: Setup GitHub CI/CD Push-to-Deploy

With CI/CD active, whenever you push changes from your local computer to GitHub, the VM will automatically deploy the latest code and restart the bot.

### Step 1: Gather Secrets
You need 3 secrets to allow GitHub to deploy securely:
1. **VM IP**: Your Azure VM's Public IP address.
2. **VM Username**: `azureuser`.
3. **SSH Key**: The exact contents of your downloaded `.pem` key file. Open your `.pem` file in a text editor (e.g. Notepad) and copy the entire text starting with `-----BEGIN OPENSSH PRIVATE KEY-----` and ending with `-----END OPENSSH PRIVATE KEY-----`.

### Step 2: Configure Secrets in GitHub
1. Go to your repository page on [GitHub](https://github.com/).
2. Click **Settings** -> **Secrets and variables** -> **Actions** (under the security section in the sidebar).
3. Click the **New repository secret** button.
4. Add the following three secrets:
   - **`VM_HOST`** -> Paste your **VM Public IP**.
   - **`VM_USERNAME`** -> Enter **`azureuser`**.
   - **`VM_SSH_KEY`** -> Paste the entire contents of your **Private Key `.pem` file**.

### Step 3: Test Push-to-Deploy
Make any minor change locally (e.g. a comment in a file), commit, and push it to your `main` or `master` branch:
```bash
git add .
git commit -m "Testing automatic deployment"
git push origin main
```
1. Go to the **Actions** tab on your GitHub repository page.
2. You will see the **Deploy Automator to Azure VM** workflow running!
3. Once completed, it has securely SSH-connected into your Azure VM, pulled the latest changes, updated libraries if needed, and restarted the service automatically.
