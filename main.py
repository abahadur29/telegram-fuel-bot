from __future__ import annotations
import os
import json
from dataclasses import dataclass, field
from typing import Dict, Optional
from pathlib import Path
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    PicklePersistence,
)

# --------------------------- Config & State ---------------------------
# The bot's state will now be persisted by the PicklePersistence layer
# to this file, instead of manual JSON reads/writes.
STATE_FILE = Path("bot_state.pkl")
ALLOWED_BUCKETS = ("Aditya", "Archit")
DEFAULT_MILEAGE = 40.0  # km per liter

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN", "")
if not TOKEN:
    raise SystemExit("Missing TELEGRAM_TOKEN in environment (.env)")

@dataclass
class State:
    """
    A dataclass to hold the entire state of the bot.
    This object will be stored in context.bot_data by the persistence layer.
    """
    # map telegram user id -> bucket name ("Aditya" or "Archit")
    users: Dict[str, str] = field(default_factory=dict)
    # liters each bucket currently has contributed/available
    tank: Dict[str, float] = field(default_factory=lambda: {b: 0.0 for b in ALLOWED_BUCKETS})
    # how many liters each bucket owes to the *other* bucket
    debt: Dict[str, float] = field(default_factory=lambda: {b: 0.0 for b in ALLOWED_BUCKETS})
    # temporary ride start readings per telegram user id
    ride_start: Dict[str, float] = field(default_factory=dict)
    mileage: float = DEFAULT_MILEAGE
    last_price_per_liter: float = 0.0

# --------------------------- Helpers ---------------------------

def get_state(context: ContextTypes.DEFAULT_TYPE) -> State:
    """Helper to retrieve the state object from bot_data."""
    return context.bot_data['state']

def user_id(update: Update) -> str:
    """Returns the effective user's ID as a string."""
    return str(update.effective_user.id)

def user_bucket(uid: str, state: State) -> Optional[str]:
    """Gets the bucket name for a given user ID."""
    return state.users.get(uid)

def other_bucket(bucket: str) -> str:
    """Gets the name of the other bucket."""
    return ALLOWED_BUCKETS[1] if bucket == ALLOWED_BUCKETS[0] else ALLOWED_BUCKETS[0]

async def require_registered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    """
    A decorator-like function that checks if a user is registered.
    If not, it sends a reply and returns None. Otherwise, returns the user's bucket.
    """
    state = get_state(context)
    bucket = user_bucket(user_id(update), state)
    if not bucket:
        await update.effective_message.reply_text(
            "You're not registered yet. Use /register Aditya OR /register Archit"
        )
        return None
    return bucket

# --------------------------- Commands ---------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /start and /help commands."""
    await update.message.reply_text(
        "Hi! This bot splits fuel fairly using liter buckets.\n\n"
        "1) `/register Aditya` or `/register Archit`\n"
        "2) Start a ride: `/ride_start <odo_km>`\n"
        "3) End the ride: `/ride_end <odo_km>` (auto computes liters)\n"
        "4) When you refuel: `/fill <liters> <total_cost_rs>`\n"
        "5) Adjust mileage: `/set_mileage <km_per_liter>`\n"
        "6) Check status: `/status`\n"
        "7) Settle up: `/settle` and `/pay <amount|full>`\n"
        "8) Reset data: `/reset`"
    )

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Registers a user to a bucket (Aditya or Archit)."""
    try:
        bucket = context.args[0].strip().title()
    except IndexError:
        await update.message.reply_text("Usage: /register <Aditya|Archit>")
        return

    if bucket not in ALLOWED_BUCKETS:
        await update.message.reply_text(f"Invalid bucket. Use one of: {', '.join(ALLOWED_BUCKETS)}")
        return

    state = get_state(context)
    uid = user_id(update)
    state.users[uid] = bucket
    # No .save() needed! Persistence handles it.
    await update.message.reply_text(f"Registered you as {bucket}.")

async def set_mileage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets the vehicle's mileage."""
    if not await require_registered(update, context):
        return
    try:
        kmpl = float(context.args[0])
        if kmpl <= 0:
            raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /set_mileage <km_per_liter>, e.g. /set_mileage 40")
        return
    
    state = get_state(context)
    state.mileage = kmpl
    await update.message.reply_text(f"Mileage set to {kmpl:.2f} km/L.")

async def ride_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Records the starting odometer reading for a ride."""
    if not await require_registered(update, context):
        return
    try:
        start_km = float(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /ride_start <odometer_km>")
        return
    
    state = get_state(context)
    state.ride_start[user_id(update)] = start_km
    await update.message.reply_text(f"Ride started at {start_km} km.")

async def ride_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Records the ending odometer reading and calculates fuel used."""
    bucket = await require_registered(update, context)
    if not bucket:
        return

    state = get_state(context)
    uid = user_id(update)
    
    if uid not in state.ride_start:
        await update.message.reply_text("You haven't started a ride. Use /ride_start first.")
        return

    try:
        end_km = float(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /ride_end <odometer_km>")
        return

    start_km = state.ride_start.pop(uid)
    distance = end_km - start_km
    if distance < 0:
        await update.message.reply_text("End odometer reading can't be less than the start.")
        # Put the start reading back since the ride was invalid
        state.ride_start[uid] = start_km
        return

    if state.mileage <= 0:
        await update.message.reply_text("Cannot calculate usage: mileage is not set to a positive number.")
        return
        
    used_l = distance / state.mileage
    me, other = bucket, other_bucket(bucket)

    # Check if there's enough fuel in total across both tanks
    available_total = state.tank[me] + state.tank[other]
    if used_l > available_total + 1e-9: # Add tolerance for float precision
        await update.message.reply_text(
            f"Not enough fuel! Ride needs {used_l:.2f} L, but only {available_total:.2f} L is available in total.\n"
            "Please /fill the tank or correct the /set_mileage."
        )
        state.ride_start[uid] = start_km # Put start reading back
        return

    # Deduct from the user's bucket first, then borrow from the other
    borrowed = 0.0
    if state.tank[me] >= used_l:
        state.tank[me] -= used_l
    else:
        borrowed = used_l - state.tank[me]
        state.tank[me] = 0.0
        state.tank[other] -= borrowed
        state.debt[me] += borrowed  # "me" now owes "other" this many liters

    await update.message.reply_text(
        f"Ride of {distance:.2f} km ended.\n"
        f"Fuel used: {used_l:.2f} L.\n"
        f"Borrowed {borrowed:.2f} L from {other}'s bucket."
    )

async def fill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Records a fuel fill-up, updating tanks and debts."""
    bucket = await require_registered(update, context)
    if not bucket:
        return
    try:
        liters = float(context.args[0])
        total_cost = float(context.args[1])
        if liters <= 0 or total_cost <= 0:
            raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /fill <liters> <total_cost_rs>")
        return

    state = get_state(context)
    price = total_cost / liters
    state.last_price_per_liter = price
    other = other_bucket(bucket)
    
    # The person filling up first uses the fuel to clear their own debt
    clear_l = min(liters, state.debt[bucket])
    if clear_l > 0:
        state.debt[bucket] -= clear_l
        # The cleared liters are returned to the other person's tank
        state.tank[other] += clear_l
    
    remaining_liters = liters - clear_l
    # Any remaining fuel goes into the filler's own tank
    state.tank[bucket] += remaining_liters

    await update.message.reply_text(
        f"Fill recorded.\n"
        f"{clear_l:.2f} L used to clear your debt to {other}.\n"
        f"{remaining_liters:.2f} L added to your bucket.\n"
        f"New price set to ₹{price:.2f}/L."
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the current status of tanks and debts."""
    bucket = await require_registered(update, context)
    if not bucket:
        return
    
    state = get_state(context)
    me, other = bucket, other_bucket(bucket)
    
    # Determine who owes whom
    debt_msg = "All square!"
    if state.debt[me] > state.debt[other]:
        net_debt_l = state.debt[me] - state.debt[other]
        net_debt_rs = net_debt_l * state.last_price_per_liter
        debt_msg = f"You ({me}) owe {other} {net_debt_l:.2f} L (≈ ₹{net_debt_rs:.2f})."
    elif state.debt[other] > state.debt[me]:
        net_debt_l = state.debt[other] - state.debt[me]
        net_debt_rs = net_debt_l * state.last_price_per_liter
        debt_msg = f"{other} owes you ({me}) {net_debt_l:.2f} L (≈ ₹{net_debt_rs:.2f})."

    text = (
        f"--- *Fuel Status* ---\n"
        f"Tank ({ALLOWED_BUCKETS[0]}): {state.tank[ALLOWED_BUCKETS[0]]:.2f} L\n"
        f"Tank ({ALLOWED_BUCKETS[1]}): {state.tank[ALLOWED_BUCKETS[1]]:.2f} L\n\n"
        f"--- *Debt Status* ---\n"
        f"{debt_msg}\n\n"
        f"--- *Settings* ---\n"
        f"Mileage: {state.mileage:.2f} km/L\n"
        f"Last Fuel Price: ₹{state.last_price_per_liter:.2f}/L"
    )
    await update.message.reply_text(text)

async def settle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Calculates and shows the cash value of the user's debt."""
    bucket = await require_registered(update, context)
    if not bucket:
        return
        
    state = get_state(context)
    price = state.last_price_per_liter
    if price <= 0:
        await update.message.reply_text(
            "No price set yet. Use /fill once to set a price reference."
        )
        return
        
    liters_owed = state.debt[bucket]
    cash_value = liters_owed * price
    await update.message.reply_text(
        f"You currently owe {liters_owed:.2f} L.\n"
        f"At the last known price of ₹{price:.2f}/L, that's approx. ₹{cash_value:.2f}.\n\n"
        "To clear this, use `/pay full` or `/pay <amount_rs>`."
    )

async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pays off debt, either fully or by a specific cash amount."""
    bucket = await require_registered(update, context)
    if not bucket:
        return
    try:
        arg = context.args[0].strip().lower()
    except IndexError:
        await update.message.reply_text("Usage: /pay <amount_rs|full>")
        return

    state = get_state(context)
    price = state.last_price_per_liter
    other = other_bucket(bucket)

    if arg == "full":
        cleared_l = state.debt[bucket]
        if cleared_l <= 0:
            await update.message.reply_text("You have no debt to clear.")
            return
        state.debt[bucket] = 0.0
        # When paid in cash, the liters are conceptually "returned" to the other person's tank
        state.tank[other] += cleared_l
        await update.message.reply_text(f"Debt of {cleared_l:.2f} L cleared in full.")
        return

    try:
        amount = float(arg)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Invalid amount. Usage: /pay <amount_rs|full>")
        return

    if price <= 0:
        await update.message.reply_text(
            "Cannot process cash payment: price is unknown. "
            "Please do a /fill first to set a price reference."
        )
        return

    liters_to_clear = amount / price
    debt_before = state.debt[bucket]
    
    if debt_before < 1e-9:
        await update.message.reply_text("You have no debt to clear.")
        return
        
    actual_cleared_l = min(debt_before, liters_to_clear)
    
    state.debt[bucket] -= actual_cleared_l
    state.tank[other] += actual_cleared_l
    
    await update.message.reply_text(
        f"Paid ₹{amount:.2f}. Cleared {actual_cleared_l:.2f} L of debt.\n"
        f"Remaining debt: {state.debt[bucket]:.2f} L."
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset all bot data."""
    state = State()  # create a new default state
    context.bot_data['state'] = state
    await update.message.reply_text("Bot state has been reset. All data cleared!")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles any unknown commands."""
    await update.message.reply_text("Sorry, I didn't understand that command. Try /help")

# --------------------------- Entry point ---------------------------

async def post_init(application: Application):
    """This function runs once when the bot starts."""
    # If the bot is started for the first time, 'state' won't be in bot_data.
    # We initialize it with a new State object.
    if 'state' not in application.bot_data:
        print("Initializing new state...")
        application.bot_data['state'] = State()
    else:
        print("Loaded existing state from persistence file.")
        # This part ensures that if we add new fields to the State dataclass,
        # old persistence files are gracefully updated.
        loaded_state = application.bot_data['state']
        if not hasattr(loaded_state, 'users'): loaded_state.users = {}
        if not hasattr(loaded_state, 'tank'): loaded_state.tank = {b: 0.0 for b in ALLOWED_BUCKETS}
        if not hasattr(loaded_state, 'debt'): loaded_state.debt = {b: 0.0 for b in ALLOWED_BUCKETS}
        if not hasattr(loaded_state, 'ride_start'): loaded_state.ride_start = {}
        if not hasattr(loaded_state, 'mileage'): loaded_state.mileage = DEFAULT_MILEAGE
        if not hasattr(loaded_state, 'last_price_per_liter'): loaded_state.last_price_per_liter = 0.0


def main():
    """Sets up the bot and starts polling."""
    # We use PicklePersistence to save the bot's state.
    persistence = PicklePersistence(filepath=STATE_FILE)

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .persistence(persistence)
        .post_init(post_init) # Run our setup function on start
        .build()
    )

    # Add command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start)) # Alias /help to /start
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("set_mileage", set_mileage))
    app.add_handler(CommandHandler("ride_start", ride_start))
    app.add_handler(CommandHandler("ride_end", ride_end))
    app.add_handler(CommandHandler("fill", fill))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("settle", settle))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("reset", reset))

    # Add a handler for any command that wasn't recognized
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    print("Bot is running… Press Ctrl+C to stop.")
    app.run_polling()

if __name__ == "__main__":
    main()
