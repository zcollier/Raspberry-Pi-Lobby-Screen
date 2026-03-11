# Raspberry Pi 4 Setup from Scratch

This guide walks you through setting up a brand new Raspberry Pi 4 with a blank SD card, preparing it for the video player installation.

## What You'll Need

- Raspberry Pi 4
- Micro SD card (16GB minimum, 32GB recommended)
- SD card reader for your computer
- Computer (Windows, Mac, or Linux)
- Internet connection (for downloading OS)
- HDMI cable and monitor (for initial setup)
- USB keyboard (for initial setup)
- Power supply for Raspberry Pi 4

## Step 1: Install Raspberry Pi OS on SD Card

### Download Raspberry Pi Imager

Download the official Raspberry Pi Imager tool for your computer:

**Download from:** https://www.raspberrypi.com/software/

Available for:
- Windows
- macOS
- Linux (Ubuntu/Debian)

### Write OS to SD Card

1. **Insert your SD card** into your computer's card reader

2. **Launch Raspberry Pi Imager**

3. **Choose Device:** Select "Raspberry Pi 4"

4. **Choose OS:**
   - Click "Choose OS"
   - Select "Raspberry Pi OS (64-bit)" (recommended)
   - OR "Raspberry Pi OS Lite (64-bit)" if you want minimal installation

   > **Recommendation:** Use the regular "Raspberry Pi OS (64-bit)" as it includes the desktop environment which is needed for video playback.

5. **Choose Storage:**
   - Click "Choose Storage"
   - Select your SD card (be careful to select the correct drive!)

6. **Configure Settings (IMPORTANT):**
   - Click the **gear icon** (⚙️) or "Edit Settings" button
   - Configure the following:

   **General tab:**
   - ✅ Set hostname: `raspberrypi` (or your preferred name)
   - ✅ Set username and password:
     - Username: `pi` (recommended to keep default)
     - Password: (choose a secure password)
   - ✅ Configure wireless LAN (if using WiFi):
     - SSID: your WiFi network name
     - Password: your WiFi password
     - Wireless LAN country: your country code
   - ✅ Set locale settings:
     - Time zone: your timezone
     - Keyboard layout: your keyboard layout

   **Services tab:**
   - ✅ Enable SSH (recommended for remote access)
     - Select "Use password authentication"

7. **Write to SD Card:**
   - Click "Save" to save settings
   - Click "Yes" to apply OS customization settings
   - Click "Yes" to confirm you want to erase the SD card
   - Wait for the write and verify process (5-10 minutes)

8. **Eject the SD card** safely when complete

## Step 2: First Boot

1. **Insert the SD card** into your Raspberry Pi 4

2. **Connect peripherals:**
   - HDMI cable to monitor (use HDMI0 port - the one closest to the power port)
   - USB keyboard
   - Ethernet cable (if not using WiFi)

3. **Power on** by connecting the power supply

4. **Wait for boot** (30-60 seconds for first boot)

5. **Login:**
   - If you see a desktop, you're ready
   - If you see a login prompt:
     - Username: `pi` (or what you set)
     - Password: (the password you set)

## Step 3: Update System

Open a terminal (if using desktop, click the terminal icon in the taskbar) and run:

```bash
sudo apt-get update
sudo apt-get upgrade -y
```

This may take 5-15 minutes depending on updates available.

## Step 4: Configure Raspberry Pi Settings

Run the configuration tool:

```bash
sudo raspi-config
```

Navigate through these settings:

### 1. System Options → Boot / Auto Login
- Select: **Desktop Autologin** (Desktop GUI, automatically logged in as 'pi' user)
- This ensures the graphical environment starts on boot

### 2. Display Options → Resolution (optional)
- Set your preferred display resolution if needed
- For most digital signage, leaving it on default is fine

### 3. Advanced Options → Compositor
- Enable: **Glamor** (for better graphics performance)

### 4. Finish and Reboot
- Select "Finish"
- When prompted to reboot, select "Yes"

## Step 5: Verify Setup

After reboot, verify everything is working:

```bash
# Check Python version (should be 3.9 or higher)
python3 --version

# Check disk space
df -h

# Check you're the pi user
whoami
```

## Step 6: Transfer Video Player Files

Now you're ready to install the video player. You have several options:

### Option A: Copy files via USB drive

1. Copy the video-player files to a USB drive on your computer
2. Insert USB drive into Raspberry Pi
3. Open file manager and copy files to `/home/pi/video-player/`

### Option B: Copy files via network (SCP)

From your computer (if SSH is enabled):

```bash
# Create directory on Pi
ssh pi@raspberrypi.local "mkdir -p /home/pi/video-player"

# Copy files from your computer
scp -r /Users/zachcollier/dev/raspberry-pi-media-player/* pi@raspberrypi.local:/home/pi/video-player/
```

### Option C: Clone from Git (if you upload to a repository)

On the Raspberry Pi:

```bash
cd /home/pi
git clone https://github.com/yourusername/raspberry-pi-media-player.git video-player
```

### Option D: Manually create files

On the Raspberry Pi, create the directory and manually create each file using nano:

```bash
mkdir -p /home/pi/video-player
cd /home/pi/video-player
nano video-player.py
# (paste contents, then Ctrl+X, Y, Enter to save)
```

## Step 7: Install Video Player

Once files are on the Raspberry Pi:

```bash
cd /home/pi/video-player
bash install.sh
```

Then follow the instructions in QUICKSTART.md to:
1. Copy your video file to `/home/pi/videos/default.mp4`
2. Configure HDMI settings
3. Reboot

## Troubleshooting

### Can't connect via SSH
- Check that SSH was enabled in Raspberry Pi Imager settings
- Try: `ssh pi@raspberrypi.local` or `ssh pi@<IP-address>`
- Find IP with: `hostname -I` on the Pi terminal

### No WiFi connection
- Check WiFi credentials in Raspberry Pi Imager were correct
- Connect via Ethernet temporarily
- Reconfigure WiFi with: `sudo raspi-config` → System Options → Wireless LAN

### Display not showing
- Try the other HDMI port (Raspberry Pi 4 has 2 micro HDMI ports)
- Use HDMI0 (the one closest to the USB-C power port)

### Need to start over
- You can re-run Raspberry Pi Imager and write the OS again to the SD card

## Minimal Installation (Alternative)

If you want a lighter system without the desktop environment:

1. In Raspberry Pi Imager, choose "Raspberry Pi OS Lite (64-bit)"
2. After setup, you'll need to configure the system to work in console mode
3. Additional packages needed: `sudo apt-get install -y xorg xinit`
4. Auto-start X server - this is more complex and not recommended for beginners

**Recommendation:** Use the full Raspberry Pi OS for easier setup.

## Ready to Go!

Your Raspberry Pi is now ready for the video player installation. Proceed to QUICKSTART.md or README.md for installation instructions.
