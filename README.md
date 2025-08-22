# Fuel Split Bot for Telegram

A simple, stateful Telegram bot designed to track and split shared fuel costs between two people using a "liter bucket" system. Instead of tracking money, the bot tracks fuel in liters, allowing for fair settlement based on the latest known fuel price.

This bot is perfect for friends or partners sharing a vehicle where fuel prices can fluctuate.

---

## Features

The bot manages fuel contributions and consumption through a simple command interface.

| Command                          | Description                                                                                                               | Example                                                                   |                           |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- | ------------------------- |
| `/start` or `/help`              | Displays the welcome message and list of commands.                                                                        | `/start`                                                                  |                           |
| \`/register \<username1          | username2>\`                                                                                                              | Registers your Telegram account to one of the two allowed "fuel buckets." | `/register username1`     |
| `/ride_start <odometer_km>`      | Records the starting odometer reading for a trip.                                                                         | `/ride_start 1200`                                                        |                           |
| `/ride_end <odometer_km>`        | Records the ending odometer reading, calculates the fuel consumed, and deducts it from the appropriate buckets.           | `/ride_end 1220`                                                          |                           |
| `/fill <liters> <total_cost_rs>` | Records a fuel top-up. Clears any outstanding liter-debt first, rest goes to your bucket. Updates latest price per liter. | `/fill 10 600`                                                            |                           |
| `/set_mileage <km_per_liter>`    | Updates the vehicle's mileage (e.g., 40 km/L).                                                                            | `/set_mileage 45`                                                         |                           |
| `/status`                        | Shows the current amount of fuel in each person's bucket, net debt, mileage, and last price per liter.                    | `/status`                                                                 |                           |
| `/settle`                        | Calculates the cash value of your current debt based on the last recorded fuel price.                                     | `/settle`                                                                 |                           |
| \`/pay \<amount\_rs              | full>\`                                                                                                                   | Pays off your liter-debt either partially or fully.                       | `/pay 300` or `/pay full` |
| `/reset`                         | Completely wipes all bot data and starts fresh.                                                                           | `/reset`                                                                  |                           |

---

## How It Works: The "Liter Bucket" System

The core logic avoids tracking money directly until it's time to settle up.

1. **Fuel Buckets**: Each user (username1 and username2) has a virtual "bucket" of fuel in liters.

2. **Filling Up**: When a user pays for fuel (`/fill`), the liters are added to their bucket. If they owe fuel to the other person, that debt is cleared first.

3. **Going for a Ride**: When a user records a trip (`/ride_start` and `/ride_end`), the bot calculates the liters consumed. These liters are first taken from that user's own bucket.

4. **Borrowing**: If the user's bucket doesn't have enough fuel for the trip, the bot automatically "borrows" the remaining liters from the other person's bucket and records this as a debt in liters.

5. **Settlement**: At any time, a user can see how many liters they owe (`/status`). When they want to pay it back (`/pay`), the bot uses the price from the most recent `/fill` command to convert the liter-debt into a cash amount.

This system ensures fairness even if fuel prices change between fill-ups.

---

## Setup and Installation

Follow these steps to get your own instance of the bot running.

### Prerequisites

* Python 3.8+
* A Telegram account

### 1. Create a Telegram Bot

1. Open Telegram and search for the BotFather.
2. Start a chat with BotFather and send the `/newbot` command.
3. Follow the prompts to choose a name and username for your bot.
4. BotFather will give you a unique HTTP API token. Keep it private.

### 2. Set Up the Project

1. Clone or download the bot's Python script (`main.py`).
2. Create a file named `.env` in the same directory.
3. Add your bot token to the `.env` file (do not commit this file to GitHub):

```
TELEGRAM_TOKEN=your_bot_token_here
```

4. Install the required Python libraries:

```bash
pip install python-telegram-bot==20.7 python-dotenv
```

### 3. Run the Bot

Run the script from your terminal:

```bash
python main.py
```

You should see:

```
Bot is running… Press Ctrl+C to stop.
```

Your bot is now live and will respond to commands in Telegram.

---

## State Management

The bot is stateful. It remembers all user data, tank levels, and debts between restarts.

* This is handled by the `PicklePersistence` feature of the `python-telegram-bot` library.
* All state is automatically saved to a file named `bot_state.pkl` in the same directory as the script.
* To start completely fresh, you can either use the `/reset` command or stop the bot and delete the `bot_state.pkl` file.

