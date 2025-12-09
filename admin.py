import logging
import re
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple, Set

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from aiogram.enums import ParseMode

from config import HELPER_ID, ADMIN_ID
from database import (
	get_all_users, delete_user_from_db, get_all_sales_reports, delete_sales_report,
	add_telegram_group, get_all_telegram_groups, delete_telegram_group,
	add_google_sheet, get_all_google_sheets, delete_google_sheet, get_google_sheet_by_id,
	get_users_paginated, get_user_by_telegram_id, get_reports_by_user,
	block_user, unblock_user, check_user_blocked, update_user_name, get_user_reports_count,
	update_user_group, get_telegram_group_by_id, get_database_stats,
	get_reports_count_by_date, get_total_users_count, get_total_reports_count,
	get_confirmed_reports_count, get_pending_reports_count, get_current_password,
	update_password, update_group_google_sheet, get_reports_by_status,
	add_user_to_db, check_user_exists, update_report_status_in_db
)
from keyboards import (
	get_main_menu_reply_keyboard, get_admin_cancel_inline_keyboard,
	get_admin_menu_inline_keyboard, get_workers_list_keyboard,
	get_worker_management_keyboard, get_groups_list_keyboard,
	get_worker_groups_keyboard, get_google_sheets_keyboard,
	get_reports_stats_keyboard, get_worker_sales_back_keyboard,
	get_sheets_list_keyboard, get_sheet_management_keyboard,
	get_google_sheets_selection_keyboard, get_password_change_keyboard,
	get_settings_keyboard
)
from google_sheets_integration import (
	test_google_sheets_connection, get_reports_statistics,
	save_report_to_sheets, get_worksheet, get_sheet_info,
	clear_test_data
)

admin_router = Router()

class AdminStates(StatesGroup):
	# Guruh boshqaruvi
	waiting_for_group_link = State()
	waiting_for_group_name = State()
	waiting_for_group_sheet_selection = State()
	waiting_for_group_id_to_delete = State()
	
	# Google Sheets boshqaruvi
	waiting_for_sheet_name = State()
	waiting_for_google_sheet_url = State()
	waiting_for_google_sheet_worksheet_name = State()
	
	# Parol boshqaruvi
	waiting_for_new_password = State()
	waiting_for_password_confirmation = State()
	
	# Admin boshqaruvi
	waiting_for_new_admin_id = State()
	waiting_for_admin_name = State()
	waiting_for_admin_delete_confirmation = State()
	
	# Tasdiqlovchi boshqaruvi
	waiting_for_new_approver_id = State()
	waiting_for_approver_name = State()
	waiting_for_approver_delete_confirmation = State()
	
	# Foydalanuvchi qidirish
	waiting_for_user_search = State()
	
	# Xabar yuborish
	waiting_for_broadcast_message = State()
	waiting_for_broadcast_confirmation = State()

# Admin va tasdiqlovchilar ro'yxati
ADDITIONAL_ADMINS: Set[int] = set()
APPROVERS: Set[int] = set()  # Tasdiqlovchilar ro'yxati

def is_admin(user_id: int) -> bool:
	"""Foydalanuvchi admin ekanligini tekshirish"""
	return user_id == ADMIN_ID or user_id in ADDITIONAL_ADMINS

def is_approver(user_id: int) -> bool:
	"""Foydalanuvchi tasdiqlovchi ekanligini tekshirish"""
	return user_id == HELPER_ID or user_id in APPROVERS or is_admin(user_id)

def can_approve_reports(user_id: int) -> bool:
	"""Hisobotlarni tasdiqlash huquqi borligini tekshirish"""
	return is_admin(user_id) or is_approver(user_id)

def add_admin(user_id: int) -> bool:
	"""Yangi admin qo'shish"""
	if user_id not in ADDITIONAL_ADMINS and user_id != ADMIN_ID:
		ADDITIONAL_ADMINS.add(user_id)
		return True
	return False

def remove_admin(user_id: int) -> bool:
	"""Adminni o'chirish (asosiy adminni o'chirish mumkin emas)"""
	if user_id in ADDITIONAL_ADMINS:
		ADDITIONAL_ADMINS.remove(user_id)
		return True
	return False

def add_approver(user_id: int) -> bool:
	"""Yangi tasdiqlovchi qo'shish"""
	if user_id not in APPROVERS and user_id != HELPER_ID and not is_admin(user_id):
		APPROVERS.add(user_id)
		return True
	return False

def remove_approver(user_id: int) -> bool:
	"""Tasdiqlovchini o'chirish"""
	if user_id in APPROVERS:
		APPROVERS.remove(user_id)
		return True
	return False

def get_all_admins() -> List[int]:
	"""Barcha adminlar ro'yxati"""
	return [ADMIN_ID] + list(ADDITIONAL_ADMINS)

def get_all_approvers() -> List[int]:
	"""Barcha tasdiqlovchilar ro'yxati"""
	approvers_list = []
	if HELPER_ID != 0:
		approvers_list.append(HELPER_ID)
	approvers_list.extend(list(APPROVERS))
	return approvers_list

# ============== FORMATTERS ==============

def format_workers_list(workers: list, page: int = 1, total_pages: int = 1, total_count: int = 0) -> str:
	"""Ishchilar ro'yxatini formatlash"""
	if not workers:
		return "📂 **ISHCHILAR RO'YXATI**\n\nHozircha ishchilar yo'q"
	
	text = f"📂 **ISHCHILAR RO'YXATI**\n"
	text += f"📄 Sahifa: {page}/{total_pages} | Jami: {total_count} ta\n\n"
	
	for i, worker in enumerate(workers, 1):
		user_id, telegram_id, full_name, reg_date, is_blocked, group_name = worker
		
		status_icon = "🔒" if is_blocked else "✅"
		group_display = group_name if group_name != 'Guruh tayinlanmagan' else "❌ Tayinlanmagan"
		
		text += f"**{i}.** {status_icon} **{full_name}**\n"
		text += f"├ 🆔 ID: `{telegram_id}`\n"
		text += f"├ 👥 Guruh: {group_display}\n"
		text += f"└ 📅 Sana: {reg_date.split(' ')[0]}\n\n"
	
	text += "💡 Batafsil ma'lumot uchun raqamli tugmani bosing"
	return text

def format_groups_list(groups: list) -> str:
	"""Guruhlar ro'yxatini formatlash"""
	if not groups:
		return "🏢 **GURUHLAR**\n\nHozircha guruhlar yo'q"
	
	text = "🏢 **GURUHLAR RO'YXATI**\n\n"
	for i, group in enumerate(groups, 1):
		db_id, group_id, group_name, topic_id, google_sheet_id, sheet_name = group
		
		sheet_display = sheet_name if sheet_name != 'Sheet tayinlanmagan' else "❌ Tayinlanmagan"
		topic_display = f"#{topic_id}" if topic_id else "Yo'q"
		
		text += f"**{i}.** 📁 **{group_name}**\n"
		text += f"├ 🆔 ID: `{group_id}`\n"
		text += f"├ 📋 Mavzu: {topic_display}\n"
		text += f"└ 📊 Sheet: {sheet_display}\n\n"
	
	text += f"📊 **Jami:** {len(groups)} ta guruh"
	return text

def format_sheets_list(sheets: list) -> str:
	"""Google Sheets ro'yxatini formatlash"""
	if not sheets:
		return "📊 **GOOGLE SHEETS**\n\nHozircha sheetlar yo'q"
	
	text = "📊 **GOOGLE SHEETS RO'YXATI**\n\n"
	for i, sheet in enumerate(sheets, 1):
		sheet_id, sheet_name, spreadsheet_id, worksheet_name, is_active = sheet
		
		status_icon = "🟢" if is_active else "🔴"
		short_id = spreadsheet_id[:15] + "..." if len(spreadsheet_id) > 15 else spreadsheet_id
		
		text += f"**{i}.** {status_icon} **{sheet_name}**\n"
		text += f"├ 🆔 ID: `{short_id}`\n"
		text += f"├ 📋 Varaq: {worksheet_name}\n"
		text += f"└ 🔘 Holat: {'Faol' if is_active else 'Nofaol'}\n\n"
	
	text += f"📈 **Jami:** {len(sheets)} ta sheet"
	return text

def format_worker_sales(worker_name: str, reports: list) -> str:
	"""Ishchi sotuvlarini formatlash"""
	if not reports:
		return f"📊 **{worker_name.upper()} SOTUVLARI**\n\nHozircha sotuvlar yo'q"
	
	text = f"📊 **{worker_name.upper()} SOTUVLARI**\n\n"
	
	confirmed_count = sum(1 for r in reports if r[12] == "confirmed")
	pending_count = sum(1 for r in reports if r[12] == "pending")
	rejected_count = sum(1 for r in reports if r[12] == "rejected")
	
	text += f"📈 **STATISTIKA:**\n"
	text += f"├ ✅ Tasdiqlangan: {confirmed_count}\n"
	text += f"├ ⏳ Kutilayotgan: {pending_count}\n"
	text += f"└ ❌ Rad etilgan: {rejected_count}\n\n"
	
	text += "📋 **SO'NGGI HISOBOTLAR:**\n"
	
	for i, report in enumerate(reports[:10], 1):
		# Updated report structure with is_tashkent field
		report_id, user_telegram_id, client_name, phone_number, additional_phone_number, contract_id, contract_amount, product_type, client_location, product_image_id, submission_date, submission_timestamp, status, confirmed_by_helper_id, confirmation_timestamp, group_message_id, google_sheet_id, is_tashkent = report
		
		if status == "confirmed":
			status_icon = "✅"
		elif status == "pending":
			status_icon = "⏳"
		elif status == "rejected":
			status_icon = "❌"
		else:
			status_icon = "❓"
		
		client_short = client_name[:20] + "..." if len(client_name) > 20 else client_name
		product_short = product_type[:25] + "..." if len(product_type) > 25 else product_type
		location_icon = "🏙️" if is_tashkent else "📍"
		
		text += f"**{i}.** {status_icon} ID: #{report_id}\n"
		text += f"├ 👤 {client_short}\n"
		text += f"├ 🛍️ {product_short}\n"
		text += f"├ {location_icon} {client_location}\n"
		text += f"├ 📄 {contract_id}\n"
		text += f"└ 📅 {submission_date}\n\n"
	
	if len(reports) > 10:
		text += f"➕ ... va yana {len(reports) - 10} ta hisobot"
	
	return text

def format_system_info() -> str:
	"""Tizim ma'lumotlarini formatlash"""
	current_time = datetime.now()
	
	text = "🖥️ **TIZIM MA'LUMOTLARI**\n\n"
	text += f"📅 **Sana:** {current_time.strftime('%d.%m.%Y')}\n"
	text += f"🕐 **Vaqt:** {current_time.strftime('%H:%M:%S')}\n"
	text += f"🤖 **Bot versiyasi:** v2.1 Pro\n"
	text += f"🐍 **Python:** 3.11+\n"
	text += f"📱 **Aiogram:** 3.x\n"
	text += f"🗄️ **Ma'lumotlar bazasi:** SQLite3\n"
	text += f"📊 **Google Sheets:** gspread\n"
	text += f"🏙️ **Toshkent shahar:** Faol\n"
	text += f"🔧 **Holat:** ✅ Ishlamoqda\n\n"
	
	# Admin va tasdiqlovchilar statistikasi
	admin_count = len(get_all_admins())
	approver_count = len(get_all_approvers())
	text += f"👨‍💻 **Adminlar:** {admin_count} ta\n"
	text += f"✅ **Tasdiqlovchilar:** {approver_count} ta\n"
	text += f"🔐 **Asosiy admin:** `{ADMIN_ID}`\n"
	
	if ADDITIONAL_ADMINS:
		text += f"➕ **Qo'shimcha adminlar:** {len(ADDITIONAL_ADMINS)} ta\n"
	
	if APPROVERS:
		text += f"✅ **Qo'shimcha tasdiqlovchilar:** {len(APPROVERS)} ta"
	
	return text

async def format_database_info() -> str:
	"""Ma'lumotlar bazasi ma'lumotlarini formatlash"""
	try:
		stats = await get_database_stats()
		
		text = "🗄️ **MA'LUMOTLAR BAZASI**\n\n"
		text += f"👥 **Foydalanuvchilar:** {stats.get('total_users', 0)} ta\n"
		text += f"📝 **Jami hisobotlar:** {stats.get('total_reports', 0)} ta\n"
		text += f"✅ **Tasdiqlangan:** {stats.get('confirmed_reports', 0)} ta\n"
		text += f"⏳ **Kutilayotgan:** {stats.get('pending_reports', 0)} ta\n"
		text += f"📅 **Bugungi hisobotlar:** {stats.get('today_reports', 0)} ta\n"
		text += f"🎯 **Tasdiqlash foizi:** {stats.get('confirmation_rate', 0)}%\n\n"
		
		# Toshkent shahar statistikasi
		text += f"🏙️ **TOSHKENT SHAHAR:**\n"
		text += f"├ Toshkent hisobotlari: {stats.get('tashkent_reports', 0)} ta\n"
		text += f"└ Boshqa hududlar: {stats.get('other_reports', 0)} ta\n\n"
		
		# Haftalik va oylik statistika
		today = date.today()
		week_ago = today - timedelta(days=7)
		month_ago = today - timedelta(days=30)
		
		week_reports = await get_reports_count_by_date(week_ago.isoformat(), today.isoformat())
		month_reports = await get_reports_count_by_date(month_ago.isoformat(), today.isoformat())
		
		text += f"📈 **Haftalik:** {week_reports} ta hisobot\n"
		text += f"📊 **Oylik:** {month_reports} ta hisobot\n"
		
		return text
	
	except Exception as e:
		logging.error(f"Ma'lumotlar bazasi ma'lumotlarini olishda xatolik: {e}")
		return "🗄️ **MA'LUMOTLAR BAZASI**\n\n❌ Ma'lumotlarni olishda xatolik"

def format_admins_list() -> str:
	"""Adminlar ro'yxatini formatlash"""
	admins = get_all_admins()
	
	text = "👨‍💻 **ADMINLAR RO'YXATI**\n\n"
	
	for i, admin_id in enumerate(admins, 1):
		if admin_id == ADMIN_ID:
			text += f"**{i}.** 👑 **Asosiy Admin**\n"
			text += f"├ 🆔 ID: `{admin_id}`\n"
			text += f"├ 🔐 Huquqlar: To'liq\n"
			text += f"└ 🚫 O'chirish: Mumkin emas\n\n"
		else:
			text += f"**{i}.** 👨‍💻 **Qo'shimcha Admin**\n"
			text += f"├ 🆔 ID: `{admin_id}`\n"
			text += f"├ 🔐 Huquqlar: To'liq\n"
			text += f"└ 🗑️ O'chirish: Mumkin\n\n"
	
	text += f"📊 **Jami:** {len(admins)} ta admin"
	return text

def format_approvers_list() -> str:
	"""Tasdiqlovchilar ro'yxatini formatlash"""
	approvers = get_all_approvers()
	
	text = "✅ **TASDIQLOVCHILAR RO'YXATI**\n\n"
	
	if not approvers:
		return text + "Hozircha tasdiqlovchilar yo'q"
	
	for i, approver_id in enumerate(approvers, 1):
		if approver_id == HELPER_ID:
			text += f"**{i}.** 🔧 **Asosiy Tasdiqlovchi**\n"
			text += f"├ 🆔 ID: `{approver_id}`\n"
			text += f"├ 🔐 Huquqlar: Hisobotlarni tasdiqlash\n"
			text += f"└ 🚫 O'chirish: Mumkin emas\n\n"
		else:
			text += f"**{i}.** ✅ **Qo'shimcha Tasdiqlovchi**\n"
			text += f"├ 🆔 ID: `{approver_id}`\n"
			text += f"├ 🔐 Huquqlar: Hisobotlarni tasdiqlash\n"
			text += f"└ 🗑️ O'chirish: Mumkin\n\n"
	
	text += f"📊 **Jami:** {len(approvers)} ta tasdiqlovchi"
	return text

# ============== KEYBOARDS ==============

def get_enhanced_admin_menu_keyboard() -> InlineKeyboardMarkup:
	"""Kengaytirilgan admin menyu klaviaturasi"""
	buttons = [
		[
			InlineKeyboardButton(text="👥 Ishchilar", callback_data="admin_workers"),
			InlineKeyboardButton(text="📊 Hisobotlar", callback_data="admin_reports")
		],
		[
			InlineKeyboardButton(text="🏢 Guruhlar", callback_data="admin_groups"),
			InlineKeyboardButton(text="📈 Google Sheets", callback_data="admin_sheets")
		],
		[
			InlineKeyboardButton(text="✅ Tasdiqlovchilar", callback_data="admin_approvers"),
			InlineKeyboardButton(text="📊 Statistika", callback_data="admin_analytics")
		],
		[
			InlineKeyboardButton(text="📢 Xabar yuborish", callback_data="admin_broadcast"),
			InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="admin_settings")
		],
		[
			InlineKeyboardButton(text="🚪 Chiqish", callback_data="admin_exit")
		]
	]
	return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_workers_list_keyboard_with_pagination(workers: list, page: int = 1,
                                              total_pages: int = 1) -> InlineKeyboardMarkup:
	"""Sahifalash bilan ishchilar ro'yxati klaviaturasi"""
	buttons = []
	
	# Raqamli tugmalar
	number_buttons = []
	for i, worker in enumerate(workers, 1):
		user_id, telegram_id, full_name, reg_date, is_blocked, group_name = worker
		number_buttons.append(InlineKeyboardButton(
			text=str(i),
			callback_data=f"worker_select_{telegram_id}"
		))
	
	# Raqamli tugmalarni 5 tadan qilib qo'yish
	for i in range(0, len(number_buttons), 5):
		buttons.append(number_buttons[i:i + 5])
	
	# Sahifalash tugmalari
	pagination_buttons = []
	if page > 1:
		pagination_buttons.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"workers_page_{page - 1}"))
	
	pagination_buttons.append(InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="current_page"))
	
	if page < total_pages:
		pagination_buttons.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"workers_page_{page + 1}"))
	
	if pagination_buttons:
		buttons.append(pagination_buttons)
	
	# Orqaga tugmasi
	buttons.append([InlineKeyboardButton(text="🔙 Admin menyu", callback_data="admin_menu")])
	
	return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_management_keyboard() -> InlineKeyboardMarkup:
	"""Admin boshqaruvi klaviaturasi"""
	buttons = [
		[
			InlineKeyboardButton(text="📋 Adminlar ro'yxati", callback_data="admins_list"),
			InlineKeyboardButton(text="➕ Admin qo'shish", callback_data="admin_add")
		],
		[
			InlineKeyboardButton(text="🗑️ Admin o'chirish", callback_data="admin_remove"),
			InlineKeyboardButton(text="🔐 Huquqlar", callback_data="admin_permissions")
		],
		[
			InlineKeyboardButton(text="🔙 Sozlamalar", callback_data="admin_settings")
		]
	]
	return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_approvers_management_keyboard() -> InlineKeyboardMarkup:
	"""Tasdiqlovchilar boshqaruvi klaviaturasi"""
	buttons = [
		[
			InlineKeyboardButton(text="📋 Tasdiqlovchilar ro'yxati", callback_data="approvers_list"),
			InlineKeyboardButton(text="➕ Tasdiqlovchi qo'shish", callback_data="approver_add")
		],
		[
			InlineKeyboardButton(text="🗑️ Tasdiqlovchi o'chirish", callback_data="approver_remove"),
			InlineKeyboardButton(text="🔐 Huquqlar", callback_data="approver_permissions")
		],
		[
			InlineKeyboardButton(text="🔙 Admin menyu", callback_data="admin_menu")
		]
	]
	return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_enhanced_settings_keyboard() -> InlineKeyboardMarkup:
	"""Kengaytirilgan sozlamalar klaviaturasi"""
	buttons = [
		[
			InlineKeyboardButton(text="👨‍💻 Admin boshqaruvi", callback_data="admin_management"),
			InlineKeyboardButton(text="✅ Tasdiqlovchilar", callback_data="admin_approvers")
		],
		[
			InlineKeyboardButton(text="🔐 Parol sozlamalari", callback_data="admin_change_password"),
			InlineKeyboardButton(text="🖥️ Tizim ma'lumotlari", callback_data="system_info")
		],
		[
			InlineKeyboardButton(text="🗄️ Ma'lumotlar bazasi", callback_data="database_info"),
			InlineKeyboardButton(text="📊 Umumiy statistika", callback_data="reports_general")
		],
		[
			InlineKeyboardButton(text="🔙 Admin menyu", callback_data="admin_menu")
		]
	]
	return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_analytics_keyboard() -> InlineKeyboardMarkup:
	"""Analitika klaviaturasi"""
	buttons = [
		[
			InlineKeyboardButton(text="📊 Umumiy statistika", callback_data="analytics_general"),
			InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="analytics_users")
		],
		[
			InlineKeyboardButton(text="📈 Hisobotlar", callback_data="analytics_reports"),
			InlineKeyboardButton(text="🏢 Guruhlar", callback_data="admin_groups")
		],
		[
			InlineKeyboardButton(text="📅 Kunlik", callback_data="analytics_daily"),
			InlineKeyboardButton(text="📆 Oylik", callback_data="analytics_monthly")
		],
		[
			InlineKeyboardButton(text="🔙 Admin menyu", callback_data="admin_menu")
		]
	]
	return InlineKeyboardMarkup(inline_keyboard=buttons)

# ============== MAIN HANDLERS ==============

@admin_router.message(Command("rava"))
async def handle_admin_command(message: Message, state: FSMContext):
	"""Admin panel asosiy buyruq"""
	if not is_admin(message.from_user.id):
		await message.answer("🚫 Sizda bu buyruqdan foydalanish uchun ruxsat yo'q.")
		return
	
	await state.clear()
	
	admin_type = "👑 Asosiy Admin" if message.from_user.id == ADMIN_ID else "👨‍💻 Admin"
	
	await message.answer(
		f"👨‍💻 **ADMIN PANEL v2.1**\n\n"
		f"Salom, {admin_type}!\n"
		f"🆔 ID: `{message.from_user.id}`\n"
		f"📅 Vaqt: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
		f"Kerakli bo'limni tanlang:",
		reply_markup=get_enhanced_admin_menu_keyboard(),
		parse_mode=ParseMode.MARKDOWN
	)
	logging.info(f"Admin {message.from_user.id} admin panelga kirdi")

# ============== WORKERS MANAGEMENT ==============

@admin_router.callback_query(F.data == "admin_workers")
async def show_workers(callback_query: CallbackQuery, state: FSMContext):
	"""Ishchilar ro'yxatini ko'rsatish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	await show_workers_page(callback_query, state, 1)

@admin_router.callback_query(F.data.startswith("workers_page_"))
async def show_workers_page_handler(callback_query: CallbackQuery, state: FSMContext):
	"""Ishchilar sahifasini ko'rsatish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	page = int(callback_query.data.split("_")[-1])
	await show_workers_page(callback_query, state, page)

async def show_workers_page(callback_query: CallbackQuery, state: FSMContext, page: int):
	"""Ishchilar sahifasini ko'rsatish"""
	per_page = 10
	workers, total_pages, total_count = await get_users_paginated(page, per_page)
	
	text = format_workers_list(workers, page, total_pages, total_count)
	keyboard = get_workers_list_keyboard_with_pagination(workers, page,
	                                                     total_pages) if workers else get_enhanced_admin_menu_keyboard()
	
	try:
		await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.callback_query(F.data == "current_page")
async def current_page_handler(callback_query: CallbackQuery):
	"""Joriy sahifa tugmasi bosilganda"""
	await callback_query.answer("📄 Siz hozir ushbu sahifadasiz")

@admin_router.callback_query(F.data.startswith("worker_select_"))
async def show_worker_details(callback_query: CallbackQuery, state: FSMContext):
	"""Ishchi batafsil ma'lumotlarini ko'rsatish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	telegram_id = int(callback_query.data.split("_")[-1])
	worker = await get_user_by_telegram_id(telegram_id)
	
	if not worker:
		await callback_query.answer("❌ Ishchi topilmadi!", show_alert=True)
		return
	
	user_id, telegram_id, full_name, reg_date, is_blocked, group_name = worker
	reports_count = await get_user_reports_count(telegram_id)
	
	# So'nggi faollik
	recent_reports = await get_reports_by_user(telegram_id, 1)
	last_activity = "Hech qachon"
	if recent_reports:
		last_activity = recent_reports[0][10].split(' ')[0] if recent_reports[0][10] else "Noma'lum"
	
	status_text = "🔒 **BLOKLANGAN**" if is_blocked else "✅ **FAOL**"
	group_display = group_name if group_name != 'Guruh tayinlanmagan' else "❌ Tayinlanmagan"
	
	text = f"👤 **ISHCHI MA'LUMOTLARI**\n\n"
	text += f"📝 **Ism:** {full_name}\n"
	text += f"🆔 **Telegram ID:** `{telegram_id}`\n"
	text += f"👥 **Guruh:** {group_display}\n"
	text += f"📅 **Ro'yxatdan o'tgan:** {reg_date.split(' ')[0]}\n"
	text += f"📊 **Jami hisobotlar:** {reports_count} ta\n"
	text += f"🕐 **So'nggi faollik:** {last_activity}\n"
	text += f"🔘 **Holat:** {status_text}\n\n"
	text += "💡 Kerakli amalni tanlang:"
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_worker_management_keyboard(telegram_id),
		                                       parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_worker_management_keyboard(telegram_id),
		                                    parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.callback_query(F.data.startswith("worker_sales_"))
async def show_worker_sales(callback_query: CallbackQuery, state: FSMContext):
	"""Ishchi sotuvlarini ko'rsatish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	telegram_id = int(callback_query.data.split("_")[-1])
	worker = await get_user_by_telegram_id(telegram_id)
	reports = await get_reports_by_user(telegram_id, 20)
	
	if not worker:
		await callback_query.answer("❌ Ishchi topilmadi!", show_alert=True)
		return
	
	full_name = worker[2]
	text = format_worker_sales(full_name, reports)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_worker_sales_back_keyboard(telegram_id),
		                                       parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_worker_sales_back_keyboard(telegram_id),
		                                    parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.callback_query(F.data.startswith("worker_block_"))
async def toggle_worker_block(callback_query: CallbackQuery, state: FSMContext):
	"""Ishchini bloklash/blokdan chiqarish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	telegram_id = int(callback_query.data.split("_")[-1])
	is_blocked = await check_user_blocked(telegram_id)
	
	if is_blocked:
		success = await unblock_user(telegram_id)
		message = "🔓 Ishchi blokdan chiqarildi!" if success else "❌ Xatolik yuz berdi!"
	else:
		success = await block_user(telegram_id)
		message = "🔒 Ishchi bloklandi!" if success else "❌ Xatolik yuz berdi!"
	
	await callback_query.answer(message, show_alert=True)
	
	if success:
		await show_worker_details(callback_query, state)

@admin_router.callback_query(F.data.startswith("worker_group_"))
async def change_worker_group(callback_query: CallbackQuery, state: FSMContext):
	"""Ishchi guruhini o'zgartirish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	telegram_id = int(callback_query.data.split("_")[-1])
	groups = await get_all_telegram_groups()
	
	if not groups:
		await callback_query.answer("❌ Guruhlar mavjud emas!", show_alert=True)
		return
	
	text = "👥 **GURUH TANLASH**\n\nIshchi uchun guruh tanlang:"
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_worker_groups_keyboard(groups, telegram_id),
		                                       parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_worker_groups_keyboard(groups, telegram_id),
		                                    parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.callback_query(F.data.startswith("assign_worker_"))
async def assign_worker_to_group(callback_query: CallbackQuery, state: FSMContext):
	"""Ishchini guruhga tayinlash"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	parts = callback_query.data.split("_")
	worker_telegram_id = int(parts[2])
	group_id = int(parts[3])
	
	success = await update_user_group(worker_telegram_id, group_id)
	
	if success:
		group_info = await get_telegram_group_by_id(group_id)
		group_name = group_info[2] if group_info else "Noma'lum"
		await callback_query.answer(f"✅ Ishchi '{group_name}' guruhiga tayinlandi!", show_alert=True)
		logging.info(f"Worker {worker_telegram_id} assigned to group {group_id} by admin")
	else:
		await callback_query.answer("❌ Xatolik yuz berdi!", show_alert=True)
	
	await show_worker_details(callback_query, state)

@admin_router.callback_query(F.data.startswith("worker_delete_"))
async def delete_worker(callback_query: CallbackQuery, state: FSMContext):
	"""Ishchini o'chirish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	telegram_id = int(callback_query.data.split("_")[-1])
	worker = await get_user_by_telegram_id(telegram_id)
	
	if not worker:
		await callback_query.answer("❌ Ishchi topilmadi!", show_alert=True)
		return
	
	success = await delete_user_from_db(telegram_id)
	
	if success:
		await callback_query.answer("✅ Ishchi o'chirildi!", show_alert=True)
		logging.info(f"Worker {telegram_id} deleted by admin")
		await show_workers(callback_query, state)
	else:
		await callback_query.answer("❌ Xatolik yuz berdi!", show_alert=True)

# ============== APPROVERS MANAGEMENT ==============

@admin_router.callback_query(F.data == "admin_approvers")
async def show_approvers_menu(callback_query: CallbackQuery, state: FSMContext):
	"""Tasdiqlovchilar menyusini ko'rsatish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	text = (
		"✅ **TASDIQLOVCHILAR BOSHQARUVI**\n\n"
		f"📊 Jami tasdiqlovchilar: **{len(get_all_approvers())} ta**\n\n"
		"Tasdiqlovchilar hisobotlarni tasdiqlash va rad etish huquqiga ega.\n\n"
		"💡 **Eslatma:** Admin paneldan qo'shilgan tasdiqlovchilar ham hisobotlarni tasdiqlash imkoniyatiga ega.\n\n"
		"Kerakli amalni tanlang:"
	)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_approvers_management_keyboard(),
		                                       parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_approvers_management_keyboard(),
		                                    parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.callback_query(F.data == "approvers_list")
async def show_approvers_list(callback_query: CallbackQuery, state: FSMContext):
	"""Tasdiqlovchilar ro'yxatini ko'rsatish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	text = format_approvers_list()
	
	keyboard = InlineKeyboardMarkup(inline_keyboard=[
		[InlineKeyboardButton(text="🔙 Tasdiqlovchilar", callback_data="admin_approvers")]
	])
	
	try:
		await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.callback_query(F.data == "approver_add")
async def add_approver_start(callback_query: CallbackQuery, state: FSMContext):
	"""Tasdiqlovchi qo'shishni boshlash"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	await state.set_state(AdminStates.waiting_for_new_approver_id)
	text = (
		"➕ **YANGI TASDIQLOVCHI QO'SHISH**\n\n"
		"Yangi tasdiqlovchi bo'lishi kerak bo'lgan foydalanuvchining Telegram ID'sini kiriting:\n\n"
		"📝 **Masalan:** `123456789`\n\n"
		"💡 **Eslatma:**\n"
		"• Foydalanuvchi ID'sini olish uchun @userinfobot dan foydalaning\n"
		"• Yangi tasdiqlovchi hisobotlarni tasdiqlash huquqiga ega bo'ladi\n"
		"• Tasdiqlovchi admin huquqlariga ega bo'lmaydi\n"
		"• Qo'shilgan tasdiqlovchi darhol hisobotlarni tasdiqlash imkoniyatiga ega bo'ladi"
	)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_admin_cancel_inline_keyboard(),
		                                       parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_admin_cancel_inline_keyboard(),
		                                    parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.message(AdminStates.waiting_for_new_approver_id)
async def process_new_approver_id(message: Message, state: FSMContext):
	"""Yangi tasdiqlovchi ID'sini qayta ishlash"""
	if not is_admin(message.from_user.id):
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	try:
		new_approver_id = int(message.text.strip())
	except ValueError:
		await message.answer(
			"❌ **XATO**\n\n"
			"Faqat raqamli Telegram ID kiriting\n"
			"**Masalan:** `123456789`",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	if new_approver_id == HELPER_ID:
		await message.answer(
			"⚠️ **XATO**\n\n"
			"Bu foydalanuvchi allaqachon asosiy tasdiqlovchi!",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	if is_admin(new_approver_id):
		await message.answer(
			"⚠️ **XATO**\n\n"
			"Bu foydalanuvchi admin! Adminlar avtomatik tasdiqlovchi huquqiga ega.",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	if new_approver_id in APPROVERS:
		await message.answer(
			"⚠️ **XATO**\n\n"
			"Bu foydalanuvchi allaqachon tasdiqlovchi!",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	await state.update_data(new_approver_id=new_approver_id)
	await state.set_state(AdminStates.waiting_for_approver_name)
	
	await message.answer(
		f"✅ **TASDIQLASH**\n\n"
		f"**Yangi tasdiqlovchi ID:** `{new_approver_id}`\n\n"
		f"Bu tasdiqlovchi uchun nom kiriting:\n"
		f"*(Masalan: 'Akmal Tasdiqlovchi' yoki 'Yordamchi')*",
		reply_markup=get_admin_cancel_inline_keyboard(),
		parse_mode=ParseMode.MARKDOWN
	)

@admin_router.message(AdminStates.waiting_for_approver_name)
async def process_approver_name(message: Message, state: FSMContext):
	"""Tasdiqlovchi nomini qayta ishlash"""
	if not is_admin(message.from_user.id):
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	approver_name = message.text.strip()
	if not approver_name or len(approver_name) < 2:
		await message.answer(
			"⚠️ **XATO**\n\n"
			"Tasdiqlovchi nomini to'g'ri kiriting (kamida 2 belgi)",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	data = await state.get_data()
	new_approver_id = data.get("new_approver_id")
	
	success = add_approver(new_approver_id)
	
	if success:
		text = (
			f"✅ **MUVAFFAQIYAT**\n\n"
			f"Yangi tasdiqlovchi muvaffaqiyatli qo'shildi!\n\n"
			f"✅ **Tasdiqlovchi nomi:** {approver_name}\n"
			f"🆔 **Telegram ID:** `{new_approver_id}`\n"
			f"🔐 **Huquqlar:** Hisobotlarni tasdiqlash\n"
			f"📅 **Qo'shilgan:** {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
			f"⚠️ **Eslatma:** Yangi tasdiqlovchi darhol hisobotlarni tasdiqlash imkoniyatiga ega bo'ladi.\n"
			f"🎯 **Funksiya:** Guruhda yuborilgan hisobotlarni tasdiqlash va rad etish."
		)
		logging.info(f"New approver added: {new_approver_id} ({approver_name}) by admin {message.from_user.id}")
	else:
		text = "❌ **XATO**\n\nTasdiqlovchini qo'shishda xatolik yuz berdi"
	
	await state.clear()
	await message.answer(text, parse_mode=ParseMode.MARKDOWN)
	
	# Tasdiqlovchilar ro'yxatini yangilash
	await message.answer(
		format_approvers_list(),
		reply_markup=get_approvers_management_keyboard(),
		parse_mode=ParseMode.MARKDOWN
	)

@admin_router.callback_query(F.data == "approver_remove")
async def remove_approver_start(callback_query: CallbackQuery, state: FSMContext):
	"""Tasdiqlovchi o'chirishni boshlash"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	if not APPROVERS:
		await callback_query.answer("❌ O'chiriladigan qo'shimcha tasdiqlovchilar yo'q!", show_alert=True)
		return
	
	text = (
		"🗑️ **TASDIQLOVCHI O'CHIRISH**\n\n"
		"O'chirmoqchi bo'lgan tasdiqlovchi ID'sini kiriting:\n\n"
		"**Qo'shimcha tasdiqlovchilar:**\n"
	)
	
	for i, approver_id in enumerate(APPROVERS, 1):
		text += f"{i}. ID: `{approver_id}`\n"
	
	text += "\n💡 Faqat tasdiqlovchi ID'sini kiriting"
	
	await state.set_state(AdminStates.waiting_for_approver_delete_confirmation)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_admin_cancel_inline_keyboard(),
		                                       parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_admin_cancel_inline_keyboard(),
		                                    parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.message(AdminStates.waiting_for_approver_delete_confirmation)
async def process_approver_delete(message: Message, state: FSMContext):
	"""Tasdiqlovchi o'chirishni qayta ishlash"""
	if not is_admin(message.from_user.id):
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	try:
		approver_id_to_remove = int(message.text.strip())
	except ValueError:
		await message.answer(
			"❌ **XATO**\n\n"
			"Faqat raqamli tasdiqlovchi ID kiriting",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	if approver_id_to_remove == HELPER_ID:
		await message.answer(
			"⚠️ **XATO**\n\n"
			"Asosiy tasdiqlovchini o'chirish mumkin emas!",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	if approver_id_to_remove not in APPROVERS:
		await message.answer(
			"❌ **XATO**\n\n"
			"Bunday ID'li tasdiqlovchi topilmadi",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	success = remove_approver(approver_id_to_remove)
	
	if success:
		text = (
			f"✅ **MUVAFFAQIYAT**\n\n"
			f"Tasdiqlovchi muvaffaqiyatli o'chirildi!\n\n"
			f"🆔 **O'chirilgan tasdiqlovchi ID:** `{approver_id_to_remove}`\n"
			f"📅 **O'chirilgan:** {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
			f"⚠️ **Eslatma:** Bu foydalanuvchi endi hisobotlarni tasdiqlash huquqiga ega emas."
		)
		logging.info(f"Approver removed: {approver_id_to_remove} by admin {message.from_user.id}")
	else:
		text = "❌ **XATO**\n\nTasdiqlovchini o'chirishda xatolik yuz berdi"
	
	await state.clear()
	await message.answer(text, parse_mode=ParseMode.MARKDOWN)
	
	# Tasdiqlovchilar ro'yxatini yangilash
	await message.answer(
		format_approvers_list(),
		reply_markup=get_approvers_management_keyboard(),
		parse_mode=ParseMode.MARKDOWN
	)

@admin_router.callback_query(F.data == "approver_permissions")
async def show_approver_permissions(callback_query: CallbackQuery, state: FSMContext):
	"""Tasdiqlovchi huquqlarini ko'rsatish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	text = (
		"🔐 **TASDIQLOVCHI HUQUQLARI**\n\n"
		"**🔧 Asosiy Tasdiqlovchi (Helper):**\n"
		"├ ✅ Hisobotlarni tasdiqlash\n"
		"├ ✅ Hisobotlarni rad etish\n"
		"├ ✅ Sotuvchi bilan bog'lanish\n"
		"├ ✅ Guruhda hisobotlarni ko'rish\n"
		"├ ❌ Admin funksiyalari\n"
		"└ 🚫 O'chirish mumkin emas\n\n"
		
		"**✅ Qo'shimcha Tasdiqlovchilar:**\n"
		"├ ✅ Hisobotlarni tasdiqlash\n"
		"├ ✅ Hisobotlarni rad etish\n"
		"├ ✅ Sotuvchi bilan bog'lanish\n"
		"├ ✅ Guruhda hisobotlarni ko'rish\n"
		"├ ❌ Admin funksiyalari\n"
		"└ 🗑️ O'chirish mumkin\n\n"
		
		"**👨‍💻 Adminlar:**\n"
		"├ ✅ Barcha tasdiqlovchi huquqlari\n"
		"├ ✅ Barcha admin funksiyalari\n"
		"├ ✅ Tasdiqlovchilarni boshqarish\n"
		"└ ✅ To'liq nazorat\n\n"
		
		f"📊 **Jami tasdiqlovchilar:** {len(get_all_approvers())} ta\n"
		f"🔧 **Asosiy tasdiqlovchi:** {'1 ta' if HELPER_ID != 0 else '0 ta'}\n"
		f"✅ **Qo'shimcha tasdiqlovchilar:** {len(APPROVERS)} ta\n\n"
		
		f"💡 **Eslatma:** Barcha tasdiqlovchilar guruhda yuborilgan hisobotlarni tasdiqlash yoki rad etish imkoniyatiga ega."
	)
	
	await callback_query.answer(text, show_alert=True)

# ============== GROUPS MANAGEMENT ==============

@admin_router.callback_query(F.data == "admin_groups")
async def show_groups(callback_query: CallbackQuery, state: FSMContext):
	"""Guruhlar ro'yxatini ko'rsatish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	groups = await get_all_telegram_groups()
	text = format_groups_list(groups)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_groups_list_keyboard(groups),
		                                       parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_groups_list_keyboard(groups),
		                                    parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.callback_query(F.data == "group_add")
async def add_group_start(callback_query: CallbackQuery, state: FSMContext):
	"""Guruh qo'shishni boshlash"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	await state.set_state(AdminStates.waiting_for_group_link)
	text = (
		"➕ **GURUH QO'SHISH**\n\n"
		"Guruh yoki mavzuning havolasini kiriting:\n\n"
		"📝 **Masalan:**\n"
		"• `https://t.me/c/1234567890/123` (mavzu bilan)\n"
		"• `https://t.me/c/1234567890` (mavzusiz)\n"
		"• `-1001234567890` (raqamli ID)\n\n"
		"💡 Guruh ID'sini olish uchun botni guruhga qo'shing va /rava buyrug'ini yuboring"
	)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_admin_cancel_inline_keyboard(),
		                                       parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_admin_cancel_inline_keyboard(),
		                                    parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.message(AdminStates.waiting_for_group_link)
async def process_group_link(message: Message, state: FSMContext):
	"""Guruh havolasini qayta ishlash"""
	if not is_admin(message.from_user.id):
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	link = message.text.strip()
	group_id = None
	topic_id = None
	
	match_channel_topic = re.match(r"https://t\.me/c/(\d+)/(\d+)", link)
	match_channel_no_topic = re.match(r"https://t\.me/c/(\d+)", link)
	match_numeric_id = re.match(r"^-?\d+$", link)
	
	if match_channel_topic:
		group_id = int("-100" + match_channel_topic.group(1))
		topic_id = int(match_channel_topic.group(2))
	elif match_channel_no_topic:
		group_id = int("-100" + match_channel_no_topic.group(1))
		topic_id = None
	elif match_numeric_id:
		group_id = int(link)
		topic_id = None
	else:
		await message.answer(
			"❌ **XATO**\n\n"
			"Noto'g'ri havola kiritildi\n\n"
			"**To'g'ri formatlar:**\n"
			"• `https://t.me/c/GROUP_ID/TOPIC_ID`\n"
			"• `https://t.me/c/GROUP_ID`\n"
			"• `-1001234567890`",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	if group_id:
		await state.update_data(temp_group_id=group_id, temp_topic_id=topic_id)
		await state.set_state(AdminStates.waiting_for_group_name)
		await message.answer(
			f"✅ **TASDIQLASH**\n\n"
			f"**Guruh ID:** `{group_id}`\n"
			f"**Mavzu ID:** {topic_id if topic_id else 'Yo\'q'}\n\n"
			f"Endi bu guruh uchun nom kiriting:\n"
			f"*(Masalan: 'Asosiy Sotuv Hisoboti')*",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)

@admin_router.message(AdminStates.waiting_for_group_name)
async def process_group_name(message: Message, state: FSMContext):
	"""Guruh nomini qayta ishlash"""
	if not is_admin(message.from_user.id):
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	group_name = message.text.strip()
	if not group_name or len(group_name) < 3:
		await message.answer(
			"⚠️ **XATO**\n\n"
			"Guruh nomini to'g'ri kiriting (kamida 3 belgi)",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	await state.update_data(temp_group_name=group_name)
	
	sheets = await get_all_google_sheets()
	if not sheets:
		await message.answer(
			"⚠️ **XATO**\n\n"
			"Hozircha Google Sheets mavjud emas.\n"
			"Avval Google Sheet qo'shing.",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	await state.set_state(AdminStates.waiting_for_group_sheet_selection)
	await message.answer(
		f"📊 **GOOGLE SHEET TANLASH**\n\n"
		f"**'{group_name}'** guruhi uchun Google Sheet tanlang:\n\n"
		f"Bu guruhga yuborilgan hisobotlar tanlangan Google Sheets'ga saqlanadi.",
		reply_markup=get_google_sheets_selection_keyboard(sheets),
		parse_mode=ParseMode.MARKDOWN
	)

@admin_router.callback_query(AdminStates.waiting_for_group_sheet_selection, F.data.startswith("select_sheet_"))
async def process_group_sheet_selection(callback_query: CallbackQuery, state: FSMContext):
	"""Guruh uchun Google Sheet tanlash"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	sheet_id = int(callback_query.data.split("_")[-1])
	data = await state.get_data()
	group_id = data.get("temp_group_id")
	topic_id = data.get("temp_topic_id")
	group_name = data.get("temp_group_name")
	
	sheet_info = await get_google_sheet_by_id(sheet_id)
	if not sheet_info:
		await callback_query.answer("❌ Google Sheet topilmadi!", show_alert=True)
		return
	
	sheet_name = sheet_info[1]
	
	success = await add_telegram_group(group_id, group_name, topic_id, sheet_id)
	
	if success:
		text = (
			f"✅ **MUVAFFAQIYAT**\n\n"
			f"Guruh **'{group_name}'** muvaffaqiyatli qo'shildi\n\n"
			f"📊 **Guruh ID:** `{group_id}`\n"
			f"📝 **Mavzu ID:** {topic_id if topic_id else 'Yo\'q'}\n"
			f"📈 **Google Sheet:** {sheet_name}\n\n"
			f"Bu guruhga yuborilgan hisobotlar **'{sheet_name}'** Google Sheets'ga saqlanadi."
		)
		logging.info(f"Group {group_name} ({group_id}) added with Google Sheet {sheet_name} by admin")
	else:
		text = (
			"❌ **XATO**\n\n"
			"Guruhni qo'shishda xatolik yuz berdi yoki bu guruh allaqachon mavjud"
		)
	
	await state.clear()
	await callback_query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
	
	groups = await get_all_telegram_groups()
	await callback_query.message.answer(
		format_groups_list(groups),
		reply_markup=get_groups_list_keyboard(groups),
		parse_mode=ParseMode.MARKDOWN
	)
	await callback_query.answer()

@admin_router.callback_query(F.data == "group_delete")
async def delete_group_start(callback_query: CallbackQuery, state: FSMContext):
	"""Guruh o'chirishni boshlash"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	groups = await get_all_telegram_groups()
	if not groups:
		await callback_query.answer("❌ O'chiriladigan guruhlar yo'q!", show_alert=True)
		return
	
	await state.set_state(AdminStates.waiting_for_group_id_to_delete)
	text = (
		"🗑️ **GURUH O'CHIRISH**\n\n"
		"O'chirmoqchi bo'lgan guruh ID'sini kiriting:\n\n"
	)
	
	for i, group in enumerate(groups, 1):
		db_id, group_id, group_name, topic_id, google_sheet_id, sheet_name = group
		text += f"**{i}.** {group_name} - ID: `{group_id}`\n"
	
	text += "\n💡 Faqat guruh ID'sini kiriting *(masalan: -1001234567890)*"
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_admin_cancel_inline_keyboard(),
		                                       parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_admin_cancel_inline_keyboard(),
		                                    parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.message(AdminStates.waiting_for_group_id_to_delete)
async def process_group_delete(message: Message, state: FSMContext):
	"""Guruh o'chirishni qayta ishlash"""
	if not is_admin(message.from_user.id):
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	try:
		group_id = int(message.text.strip())
	except ValueError:
		await message.answer(
			"❌ **XATO**\n\n"
			"Faqat raqamli guruh ID'sini kiriting\n"
			"**Masalan:** `-1001234567890`",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	group_info = await get_telegram_group_by_id(group_id)
	if not group_info:
		await message.answer(
			"❌ **XATO**\n\n"
			"Bunday ID'li guruh topilmadi",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	group_name = group_info[2]
	success = await delete_telegram_group(group_id)
	
	if success:
		text = f"✅ **MUVAFFAQIYAT**\n\nGuruh **'{group_name}'** o'chirildi"
		logging.info(f"Group {group_name} ({group_id}) deleted by admin")
	else:
		text = "❌ **XATO**\n\nGuruhni o'chirishda xatolik yuz berdi"
	
	await state.clear()
	await message.answer(text, parse_mode=ParseMode.MARKDOWN)
	
	groups = await get_all_telegram_groups()
	await message.answer(
		format_groups_list(groups),
		reply_markup=get_groups_list_keyboard(groups),
		parse_mode=ParseMode.MARKDOWN
	)

# ============== GOOGLE SHEETS MANAGEMENT ==============

@admin_router.callback_query(F.data == "admin_sheets")
async def show_google_sheets_menu(callback_query: CallbackQuery, state: FSMContext):
	"""Google Sheets menyusini ko'rsatish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	sheets = await get_all_google_sheets()
	
	text = (
		"📈 **GOOGLE SHEETS BOSHQARUVI**\n\n"
		f"📊 Jami faol sheetlar: **{len(sheets)} ta**\n\n"
		"Kerakli amalni tanlang:"
	)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_google_sheets_keyboard(),
		                                       parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_google_sheets_keyboard(),
		                                    parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.callback_query(F.data == "sheets_list")
async def show_sheets_list(callback_query: CallbackQuery, state: FSMContext):
	"""Google Sheets ro'yxatini ko'rsatish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	sheets = await get_all_google_sheets()
	text = format_sheets_list(sheets)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_sheets_list_keyboard(sheets),
		                                       parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_sheets_list_keyboard(sheets),
		                                    parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.callback_query(F.data == "sheets_add")
async def add_sheet_start(callback_query: CallbackQuery, state: FSMContext):
	"""Google Sheet qo'shishni boshlash"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	await state.set_state(AdminStates.waiting_for_sheet_name)
	text = (
		"➕ **GOOGLE SHEET QO'SHISH**\n\n"
		"Avval Google Sheet uchun nom kiriting:\n\n"
		"📝 **Masalan:**\n"
		"• Asosiy Hisobotlar\n"
		"• Toshkent Filiali\n"
		"• Samarqand Bo'limi\n\n"
		"💡 Bu nom guruhlar ro'yxatida ko'rinadi"
	)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_admin_cancel_inline_keyboard(),
		                                       parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_admin_cancel_inline_keyboard(),
		                                    parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.message(AdminStates.waiting_for_sheet_name)
async def process_sheet_name(message: Message, state: FSMContext):
	"""Google Sheet nomini qayta ishlash"""
	if not is_admin(message.from_user.id):
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	sheet_name = message.text.strip()
	if not sheet_name or len(sheet_name) < 3:
		await message.answer(
			"⚠️ **XATO**\n\n"
			"Sheet nomini to'g'ri kiriting (kamida 3 belgi)",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	await state.update_data(temp_sheet_name=sheet_name)
	await state.set_state(AdminStates.waiting_for_google_sheet_url)
	
	await message.answer(
		f"🔗 **GOOGLE SHEET HAVOLASI**\n\n"
		f"**'{sheet_name}'** uchun Google Sheet havolasini kiriting:\n\n"
		f"📝 **Masalan:**\n"
		f"`https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit#gid=SHEET_ID`\n\n"
		f"💡 Sheet'ni service account email bilan ulashing:\n"
		f"`web-malumotlari@aqueous-argon-454316-h5.iam.gserviceaccount.com`",
		reply_markup=get_admin_cancel_inline_keyboard(),
		parse_mode=ParseMode.MARKDOWN
	)

@admin_router.message(AdminStates.waiting_for_google_sheet_url)
async def process_google_sheet_url(message: Message, state: FSMContext):
	"""Google Sheet URL'ini qayta ishlash"""
	if not is_admin(message.from_user.id):
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	url = message.text.strip()
	match = re.search(r"https://docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
	
	if match:
		spreadsheet_id = match.group(1)
		await state.update_data(temp_spreadsheet_id=spreadsheet_id)
		await state.set_state(AdminStates.waiting_for_google_sheet_worksheet_name)
		
		await message.answer(
			f"✅ **TASDIQLASH**\n\n"
			f"Google Sheet ID qabul qilindi:\n"
			f"`{spreadsheet_id}`\n\n"
			f"Endi ishchi varaq nomini kiriting:\n"
			f"*(masalan: 'Sheet1' yoki 'Hisobotlar')*",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
	else:
		await message.answer(
			"❌ **XATO**\n\n"
			"Noto'g'ri Google Sheet havolasi\n\n"
			"**To'g'ri format:**\n"
			"`https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit`",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)

@admin_router.message(AdminStates.waiting_for_google_sheet_worksheet_name)
async def process_google_sheet_worksheet_name(message: Message, state: FSMContext):
	"""Google Sheet worksheet nomini qayta ishlash"""
	if not is_admin(message.from_user.id):
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	worksheet_name = message.text.strip()
	if not worksheet_name:
		await message.answer(
			"⚠️ **XATO**\n\n"
			"Ishchi varaq nomini kiriting\n"
			"Qaytadan kiriting",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	data = await state.get_data()
	sheet_name = data.get("temp_sheet_name")
	spreadsheet_id = data.get("temp_spreadsheet_id")
	
	try:
		worksheet = get_worksheet(spreadsheet_id, worksheet_name)
		if worksheet:
			success = await add_google_sheet(sheet_name, spreadsheet_id, worksheet_name)
			if success:
				text = (
					f"✅ **MUVAFFAQIYAT**\n\n"
					f"Google Sheet **'{sheet_name}'** muvaffaqiyatli qo'shildi\n\n"
					f"📊 **Nom:** {sheet_name}\n"
					f"📄 **ID:** `{spreadsheet_id}`\n"
					f"📋 **Varaq:** {worksheet_name}\n\n"
					f"Endi bu Sheet'ni guruhlarga tayinlashingiz mumkin."
				)
				logging.info(f"Google Sheet added: {sheet_name} ({spreadsheet_id}/{worksheet_name})")
			else:
				text = "❌ **XATO**\n\nMa'lumotlar bazasiga saqlashda xatolik yoki bu Sheet allaqachon mavjud"
		else:
			text = (
				"❌ **ULANISH XATOSI**\n\n"
				"Google Sheet'ga ulanib bo'lmadi.\n\n"
				"**Tekshiring:**\n"
				"• Sheet ID to'g'ri ekanligini\n"
				"• Service account'ga ruxsat berilganligini\n"
				"• Varaq nomi to'g'ri ekanligini"
			)
	except Exception as e:
		text = f"❌ **XATO**\n\nUlanishda xatolik: {str(e)}"
		logging.error(f"Google Sheets connection error: {e}")
	
	await state.clear()
	await message.answer(text, parse_mode=ParseMode.MARKDOWN)
	
	sheets = await get_all_google_sheets()
	await message.answer(
		format_sheets_list(sheets),
		reply_markup=get_sheets_list_keyboard(sheets),
		parse_mode=ParseMode.MARKDOWN
	)

@admin_router.callback_query(F.data.startswith("sheet_select_"))
async def show_sheet_details(callback_query: CallbackQuery, state: FSMContext):
	"""Google Sheet batafsil ma'lumotlarini ko'rsatish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	sheet_id = int(callback_query.data.split("_")[-1])
	sheet_info = await get_google_sheet_by_id(sheet_id)
	
	if not sheet_info:
		await callback_query.answer("❌ Sheet topilmadi!", show_alert=True)
		return
	
	sheet_db_id, sheet_name, spreadsheet_id, worksheet_name, is_active = sheet_info
	
	# Sheet ma'lumotlarini olish
	try:
		sheet_details = get_sheet_info(spreadsheet_id)
		total_rows = 0
		if sheet_details and sheet_details.get('worksheets'):
			for ws in sheet_details['worksheets']:
				if ws['title'] == worksheet_name:
					total_rows = ws.get('data_count', 0)
					break
	except:
		total_rows = 0
	
	text = f"📊 **GOOGLE SHEET MA'LUMOTLARI**\n\n"
	text += f"📝 **Nom:** {sheet_name}\n"
	text += f"📄 **Spreadsheet ID:** `{spreadsheet_id[:20]}...`\n"
	text += f"📋 **Worksheet:** {worksheet_name}\n"
	text += f"📊 **Ma'lumotlar:** {total_rows} ta qator\n"
	text += f"🔘 **Holat:** {'🟢 Faol' if is_active else '🔴 Nofaol'}\n\n"
	text += "💡 Kerakli amalni tanlang:"
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_sheet_management_keyboard(sheet_db_id),
		                                       parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_sheet_management_keyboard(sheet_db_id),
		                                    parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.callback_query(F.data.startswith("sheet_test_"))
async def test_sheet(callback_query: CallbackQuery, state: FSMContext):
	"""Google Sheet'ni test qilish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	sheet_id = int(callback_query.data.split("_")[-1])
	sheet_info = await get_google_sheet_by_id(sheet_id)
	
	if not sheet_info:
		await callback_query.answer("❌ Sheet topilmadi!", show_alert=True)
		return
	
	sheet_db_id, sheet_name, spreadsheet_id, worksheet_name, is_active = sheet_info
	
	success, message_text = test_google_sheets_connection(spreadsheet_id, worksheet_name)
	
	if success:
		await callback_query.message.answer(
			f"✅ **TEST MUVAFFAQIYATLI**\n\n{message_text}",
			parse_mode=ParseMode.MARKDOWN
		)
		await callback_query.answer("✅ Test muvaffaqiyatli bajarildi!")
		logging.info(f"Google Sheets test successful: {sheet_name} ({spreadsheet_id}/{worksheet_name})")
	else:
		await callback_query.answer(f"❌ Test muvaffaqiyatsiz: {message_text}", show_alert=True)
		logging.error(f"Google Sheets test failed: {message_text}")

@admin_router.callback_query(F.data.startswith("sheet_stats_"))
async def show_sheet_stats(callback_query: CallbackQuery, state: FSMContext):
	"""Google Sheet statistikasini ko'rsatish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	sheet_id = int(callback_query.data.split("_")[-1])
	sheet_info = await get_google_sheet_by_id(sheet_id)
	
	if not sheet_info:
		await callback_query.answer("❌ Sheet topilmadi!", show_alert=True)
		return
	
	sheet_db_id, sheet_name, spreadsheet_id, worksheet_name, is_active = sheet_info
	
	try:
		stats = get_reports_statistics(spreadsheet_id, worksheet_name)
		if stats:
			text = f"📊 **{sheet_name.upper()} STATISTIKASI**\n\n"
			text += f"📈 **Jami hisobotlar:** {stats.get('total_reports', 0)} ta\n"
			text += f"👥 **Sotuvchilar:** {len(stats.get('sellers_stats', {}))} ta\n"
			text += f"🛍️ **Mahsulotlar:** {len(stats.get('product_stats', {}))} ta\n"
			text += f"📍 **Hududlar:** {len(stats.get('location_stats', {}))} ta\n"
			text += f"📅 **Yangilangan:** {stats.get('last_updated', 'Noma\'lum')}\n\n"
			
			top_sellers = stats.get('top_sellers', {})
			if top_sellers:
				text += "🏆 **TOP SOTUVCHILAR:**\n"
				for i, (seller, count) in enumerate(list(top_sellers.items())[:5], 1):
					text += f"{i}. {seller}: {count} ta\n"
			
			top_products = stats.get('top_products', {})
			if top_products:
				text += "\n🛍️ **TOP MAHSULOTLAR:**\n"
				for i, (product, count) in enumerate(list(top_products.items())[:3], 1):
					product_short = product[:30] + "..." if len(product) > 30 else product
					text += f"{i}. {product_short}: {count} ta\n"
		else:
			text = f"📊 **{sheet_name.upper()} STATISTIKASI**\n\nMa'lumotlar topilmadi"
	except Exception as e:
		text = f"📊 **{sheet_name.upper()} STATISTIKASI**\n\nXatolik: {str(e)}"
		logging.error(f"Error getting sheet stats: {e}")
	
	await callback_query.message.answer(text, parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.callback_query(F.data.startswith("sheet_delete_"))
async def delete_sheet(callback_query: CallbackQuery, state: FSMContext):
	"""Google Sheet'ni o'chirish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	sheet_id = int(callback_query.data.split("_")[-1])
	sheet_info = await get_google_sheet_by_id(sheet_id)
	
	if not sheet_info:
		await callback_query.answer("❌ Sheet topilmadi!", show_alert=True)
		return
	
	sheet_name = sheet_info[1]
	success = await delete_google_sheet(sheet_id)
	
	if success:
		await callback_query.answer(f"✅ '{sheet_name}' Google Sheet o'chirildi!", show_alert=True)
		logging.info(f"Google Sheet deleted: {sheet_name} by admin")
		await show_sheets_list(callback_query, state)
	else:
		await callback_query.answer("❌ Xatolik yuz berdi!", show_alert=True)

@admin_router.callback_query(F.data.startswith("sheet_update_"))
async def update_sheet(callback_query: CallbackQuery, state: FSMContext):
	"""Google Sheet'ni yangilash"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	sheet_id = int(callback_query.data.split("_")[-1])
	sheet_info = await get_google_sheet_by_id(sheet_id)
	
	if not sheet_info:
		await callback_query.answer("❌ Sheet topilmadi!", show_alert=True)
		return
	
	sheet_db_id, sheet_name, spreadsheet_id, worksheet_name, is_active = sheet_info
	
	try:
		success = clear_test_data(spreadsheet_id, worksheet_name)
		if success:
			await callback_query.answer(f"🔄 '{sheet_name}' yangilandi va test ma'lumotlari tozalandi!", show_alert=True)
			logging.info(f"Google Sheet updated and cleaned: {sheet_name}")
		else:
			await callback_query.answer("⚠️ Yangilashda muammo bo'ldi!", show_alert=True)
	except Exception as e:
		await callback_query.answer(f"❌ Xatolik: {str(e)}", show_alert=True)
		logging.error(f"Error updating sheet: {e}")

# ============== ADMIN MANAGEMENT ==============

@admin_router.callback_query(F.data == "admin_management")
async def show_admin_management(callback_query: CallbackQuery, state: FSMContext):
	"""Admin boshqaruvi menyusini ko'rsatish"""
	if callback_query.from_user.id != ADMIN_ID:
		await callback_query.answer("🚫 Faqat asosiy admin bu bo'limga kira oladi!", show_alert=True)
		return
	
	text = format_admins_list()
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_admin_management_keyboard(),
		                                       parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_admin_management_keyboard(),
		                                    parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.callback_query(F.data == "admins_list")
async def show_admins_list(callback_query: CallbackQuery, state: FSMContext):
	"""Adminlar ro'yxatini ko'rsatish"""
	if callback_query.from_user.id != ADMIN_ID:
		await callback_query.answer("🚫 Faqat asosiy admin bu bo'limga kira oladi!", show_alert=True)
		return
	
	text = format_admins_list()
	await callback_query.answer(text, show_alert=True)

@admin_router.callback_query(F.data == "admin_add")
async def add_admin_start(callback_query: CallbackQuery, state: FSMContext):
	"""Admin qo'shishni boshlash"""
	if callback_query.from_user.id != ADMIN_ID:
		await callback_query.answer("🚫 Faqat asosiy admin yangi admin qo'sha oladi!", show_alert=True)
		return
	
	await state.set_state(AdminStates.waiting_for_new_admin_id)
	text = (
		"➕ **YANGI ADMIN QO'SHISH**\n\n"
		"Yangi admin bo'lishi kerak bo'lgan foydalanuvchining Telegram ID'sini kiriting:\n\n"
		"📝 **Masalan:** `123456789`\n\n"
		"💡 **Eslatma:**\n"
		"• Foydalanuvchi ID'sini olish uchun @userinfobot dan foydalaning\n"
		"• Yangi admin to'liq huquqlarga ega bo'ladi\n"
		"• Faqat siz (asosiy admin) adminlarni boshqara olasiz"
	)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_admin_cancel_inline_keyboard(),
		                                       parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_admin_cancel_inline_keyboard(),
		                                    parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.message(AdminStates.waiting_for_new_admin_id)
async def process_new_admin_id(message: Message, state: FSMContext):
	"""Yangi admin ID'sini qayta ishlash"""
	if message.from_user.id != ADMIN_ID:
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	try:
		new_admin_id = int(message.text.strip())
	except ValueError:
		await message.answer(
			"❌ **XATO**\n\n"
			"Faqat raqamli Telegram ID kiriting\n"
			"**Masalan:** `123456789`",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	if new_admin_id == ADMIN_ID:
		await message.answer(
			"⚠️ **XATO**\n\n"
			"Siz allaqachon asosiy adminsiz!",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	if new_admin_id in ADDITIONAL_ADMINS:
		await message.answer(
			"⚠️ **XATO**\n\n"
			"Bu foydalanuvchi allaqachon admin!",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	await state.update_data(new_admin_id=new_admin_id)
	await state.set_state(AdminStates.waiting_for_admin_name)
	
	await message.answer(
		f"✅ **TASDIQLASH**\n\n"
		f"**Yangi admin ID:** `{new_admin_id}`\n\n"
		f"Bu admin uchun nom kiriting:\n"
		f"*(Masalan: 'Akmal Admin' yoki 'Yordamchi Admin')*",
		reply_markup=get_admin_cancel_inline_keyboard(),
		parse_mode=ParseMode.MARKDOWN
	)

@admin_router.message(AdminStates.waiting_for_admin_name)
async def process_admin_name(message: Message, state: FSMContext):
	"""Admin nomini qayta ishlash"""
	if message.from_user.id != ADMIN_ID:
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	admin_name = message.text.strip()
	if not admin_name or len(admin_name) < 2:
		await message.answer(
			"⚠️ **XATO**\n\n"
			"Admin nomini to'g'ri kiriting (kamida 2 belgi)",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	data = await state.get_data()
	new_admin_id = data.get("new_admin_id")
	
	success = add_admin(new_admin_id)
	
	if success:
		text = (
			f"✅ **MUVAFFAQIYAT**\n\n"
			f"Yangi admin muvaffaqiyatli qo'shildi!\n\n"
			f"👨‍💻 **Admin nomi:** {admin_name}\n"
			f"🆔 **Telegram ID:** `{new_admin_id}`\n"
			f"🔐 **Huquqlar:** To'liq admin huquqlari\n"
			f"📅 **Qo'shilgan:** {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
			f"⚠️ **Eslatma:** Yangi admin darhol barcha admin funksiyalaridan foydalana oladi."
		)
		logging.info(f"New admin added: {new_admin_id} ({admin_name}) by main admin")
	else:
		text = "❌ **XATO**\n\nAdminni qo'shishda xatolik yuz berdi"
	
	await state.clear()
	await message.answer(text, parse_mode=ParseMode.MARKDOWN)
	
	# Admin ro'yxatini yangilash
	await message.answer(
		format_admins_list(),
		reply_markup=get_admin_management_keyboard(),
		parse_mode=ParseMode.MARKDOWN
	)

@admin_router.callback_query(F.data == "admin_remove")
async def remove_admin_start(callback_query: CallbackQuery, state: FSMContext):
	"""Admin o'chirishni boshlash"""
	if callback_query.from_user.id != ADMIN_ID:
		await callback_query.answer("🚫 Faqat asosiy admin adminlarni o'chira oladi!", show_alert=True)
		return
	
	if not ADDITIONAL_ADMINS:
		await callback_query.answer("❌ O'chiriladigan qo'shimcha adminlar yo'q!", show_alert=True)
		return
	
	text = (
		"🗑️ **ADMIN O'CHIRISH**\n\n"
		"O'chirmoqchi bo'lgan admin ID'sini kiriting:\n\n"
		"**Qo'shimcha adminlar:**\n"
	)
	
	for i, admin_id in enumerate(ADDITIONAL_ADMINS, 1):
		text += f"{i}. ID: `{admin_id}`\n"
	
	text += "\n💡 Faqat admin ID'sini kiriting"
	
	await state.set_state(AdminStates.waiting_for_admin_delete_confirmation)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_admin_cancel_inline_keyboard(),
		                                       parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_admin_cancel_inline_keyboard(),
		                                    parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.message(AdminStates.waiting_for_admin_delete_confirmation)
async def process_admin_delete(message: Message, state: FSMContext):
	"""Admin o'chirishni qayta ishlash"""
	if message.from_user.id != ADMIN_ID:
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	try:
		admin_id_to_remove = int(message.text.strip())
	except ValueError:
		await message.answer(
			"❌ **XATO**\n\n"
			"Faqat raqamli admin ID kiriting",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	if admin_id_to_remove == ADMIN_ID:
		await message.answer(
			"⚠️ **XATO**\n\n"
			"Asosiy adminni o'chirish mumkin emas!",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	if admin_id_to_remove not in ADDITIONAL_ADMINS:
		await message.answer(
			"❌ **XATO**\n\n"
			"Bunday ID'li admin topilmadi",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	success = remove_admin(admin_id_to_remove)
	
	if success:
		text = (
			f"✅ **MUVAFFAQIYAT**\n\n"
			f"Admin muvaffaqiyatli o'chirildi!\n\n"
			f"🆔 **O'chirilgan admin ID:** `{admin_id_to_remove}`\n"
			f"📅 **O'chirilgan:** {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
			f"⚠️ **Eslatma:** Bu foydalanuvchi endi admin huquqlariga ega emas."
		)
		logging.info(f"Admin removed: {admin_id_to_remove} by main admin")
	else:
		text = "❌ **XATO**\n\nAdminni o'chirishda xatolik yuz berdi"
	
	await state.clear()
	await message.answer(text, parse_mode=ParseMode.MARKDOWN)
	
	# Admin ro'yxatini yangilash
	await message.answer(
		format_admins_list(),
		reply_markup=get_admin_management_keyboard(),
		parse_mode=ParseMode.MARKDOWN
	)

@admin_router.callback_query(F.data == "admin_permissions")
async def show_admin_permissions(callback_query: CallbackQuery, state: FSMContext):
	"""Admin huquqlarini ko'rsatish"""
	if callback_query.from_user.id != ADMIN_ID:
		await callback_query.answer("🚫 Faqat asosiy admin bu ma'lumotni ko'ra oladi!", show_alert=True)
		return
	
	text = (
		"🔐 **ADMIN HUQUQLARI**\n\n"
		"**👑 Asosiy Admin (Siz):**\n"
		"├ ✅ Barcha admin funksiyalari\n"
		"├ ✅ Adminlarni qo'shish/o'chirish\n"
		"├ ✅ Tasdiqlovchilarni boshqarish\n"
		"├ ✅ Tizim sozlamalari\n"
		"├ ✅ Parol o'zgartirish\n"
		"└ ✅ To'liq nazorat\n\n"
		
		"**👨‍💻 Qo'shimcha Adminlar:**\n"
		"├ ✅ Ishchilarni boshqarish\n"
		"├ ✅ Guruhlarni boshqarish\n"
		"├ ✅ Google Sheets boshqaruvi\n"
		"├ ✅ Hisobotlarni ko'rish\n"
		"├ ✅ Statistika va analitika\n"
		"├ ✅ Tasdiqlovchilarni boshqarish\n"
		"├ ❌ Admin qo'shish/o'chirish\n"
		"└ ❌ Tizim sozlamalari\n\n"
		
		f"📊 **Jami adminlar:** {len(get_all_admins())} ta\n"
		f"👑 **Asosiy admin:** 1 ta\n"
		f"👨‍💻 **Qo'shimcha adminlar:** {len(ADDITIONAL_ADMINS)} ta"
	)
	
	await callback_query.answer(text, show_alert=True)

# ============== PASSWORD MANAGEMENT ==============

@admin_router.callback_query(F.data == "admin_change_password")
async def show_password_menu(callback_query: CallbackQuery, state: FSMContext):
	"""Parol boshqaruvi menyusini ko'rsatish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	current_password = await get_current_password()
	
	text = (
		"🔐 **PAROL BOSHQARUVI**\n\n"
		f"📋 **Joriy parol:** `{current_password}`\n\n"
		"⚠️ **DIQQAT:**\n"
		"• Parol o'zgarishi faqat yangi foydalanuvchilarga ta'sir qiladi\n"
		"• Mavjud foydalanuvchilar eski parol bilan kirishda davom etadilar\n"
		"• Yangi foydalanuvchilar yangi parol bilan ro'yxatdan o'tadilar\n\n"
		"Kerakli amalni tanlang:"
	)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_password_change_keyboard(),
		                                       parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_password_change_keyboard(),
		                                    parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.callback_query(F.data == "change_password_start")
async def start_password_change(callback_query: CallbackQuery, state: FSMContext):
	"""Parol o'zgartirishni boshlash"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	await state.set_state(AdminStates.waiting_for_new_password)
	text = (
		"🔐 **YANGI PAROL KIRITING**\n\n"
		"Yangi parolni kiriting:\n\n"
		"📝 **Tavsiyalar:**\n"
		"• Kamida 4 belgi\n"
		"• Oson eslab qoladigan\n"
		"• Xavfsiz bo'lishi kerak\n\n"
		"💡 **Masalan:** `2025`, `admin123`, `secure2024`"
	)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_admin_cancel_inline_keyboard(),
		                                       parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_admin_cancel_inline_keyboard(),
		                                    parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.message(AdminStates.waiting_for_new_password)
async def process_new_password(message: Message, state: FSMContext):
	"""Yangi parolni qayta ishlash"""
	if not is_admin(message.from_user.id):
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	new_password = message.text.strip()
	if not new_password or len(new_password) < 4:
		await message.answer(
			"⚠️ **XATO**\n\n"
			"Parol kamida 4 belgi bo'lishi kerak.\n"
			"Qaytadan kiriting:",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	current_password = await get_current_password()
	if new_password == current_password:
		await message.answer(
			"⚠️ **XATO**\n\n"
			"Yangi parol joriy parol bilan bir xil.\n"
			"Boshqa parol kiriting:",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	await state.update_data(new_password=new_password)
	await state.set_state(AdminStates.waiting_for_password_confirmation)
	
	await message.answer(
		f"🔐 **PAROLNI TASDIQLASH**\n\n"
		f"**Yangi parol:** `{new_password}`\n\n"
		f"Parolni tasdiqlash uchun qaytadan kiriting:",
		reply_markup=get_admin_cancel_inline_keyboard(),
		parse_mode=ParseMode.MARKDOWN
	)

@admin_router.message(AdminStates.waiting_for_password_confirmation)
async def process_password_confirmation(message: Message, state: FSMContext):
	"""Parol tasdiqlashni qayta ishlash"""
	if not is_admin(message.from_user.id):
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	confirmation = message.text.strip()
	data = await state.get_data()
	new_password = data.get("new_password")
	
	if confirmation != new_password:
		await message.answer(
			"❌ **XATO**\n\n"
			"Parollar mos kelmadi.\n"
			"Qaytadan tasdiqlash parolini kiriting:",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	success = await update_password(new_password)
	
	if success:
		text = (
			f"✅ **MUVAFFAQIYAT**\n\n"
			f"Parol muvaffaqiyatli o'zgartirildi!\n\n"
			f"📋 **Yangi parol:** `{new_password}`\n\n"
			f"⚠️ **ESLATMA:**\n"
			f"• Yangi foydalanuvchilar `{new_password}` parol bilan ro'yxatdan o'tadilar\n"
			f"• Mavjud foydalanuvchilar eski parol bilan kirishda davom etadilar\n"
			f"• Bu o'zgarish darhol kuchga kiradi"
		)
		logging.info(f"Admin password changed to: {new_password}")
	else:
		text = "❌ **XATO**\n\nParolni o'zgartirishda xatolik yuz berdi"
	
	await state.clear()
	await message.answer(text, parse_mode=ParseMode.MARKDOWN)

@admin_router.callback_query(F.data == "view_current_password")
async def view_current_password(callback_query: CallbackQuery, state: FSMContext):
	"""Joriy parolni ko'rsatish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	current_password = await get_current_password()
	await callback_query.answer(f"🔐 Joriy parol: {current_password}", show_alert=True)

# ============== REPORTS MANAGEMENT ==============

@admin_router.callback_query(F.data == "admin_reports")
async def show_reports_menu(callback_query: CallbackQuery, state: FSMContext):
	"""Hisobotlar menyusini ko'rsatish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	try:
		await callback_query.message.edit_text(
			"📊 **HISOBOTLAR**\n\nKerakli bo'limni tanlang:",
			reply_markup=get_reports_stats_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
	except TelegramBadRequest:
		await callback_query.message.answer(
			"📊 **HISOBOTLAR**\n\nKerakli bo'limni tanlang:",
			reply_markup=get_reports_stats_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
	await callback_query.answer()

@admin_router.callback_query(F.data == "reports_general")
async def show_general_reports(callback_query: CallbackQuery, state: FSMContext):
	"""Umumiy hisobotlarni ko'rsatish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	stats = await get_database_stats()
	
	today = date.today()
	week_ago = today - timedelta(days=7)
	week_reports = await get_reports_count_by_date(week_ago.isoformat(), today.isoformat())
	
	month_ago = today - timedelta(days=30)
	month_reports = await get_reports_count_by_date(month_ago.isoformat(), today.isoformat())
	
	text = (
		"📊 **UMUMIY STATISTIKA**\n\n"
		f"👥 **Jami ishchilar:** {stats.get('total_users', 0)} ta\n"
		f"📝 **Jami hisobotlar:** {stats.get('total_reports', 0)} ta\n"
		f"✅ **Tasdiqlangan:** {stats.get('confirmed_reports', 0)} ta\n"
		f"⏳ **Kutilayotgan:** {stats.get('pending_reports', 0)} ta\n"
		f"📅 **Bugungi hisobotlar:** {stats.get('today_reports', 0)} ta\n"
		f"📈 **Haftalik hisobotlar:** {week_reports} ta\n"
		f"📊 **Oylik hisobotlar:** {month_reports} ta\n"
		f"🎯 **Tasdiqlash foizi:** {stats.get('confirmation_rate', 0)}%\n\n"
		f"🏙️ **TOSHKENT SHAHAR:**\n"
		f"├ Toshkent hisobotlari: {stats.get('tashkent_reports', 0)} ta\n"
		f"└ Boshqa hududlar: {stats.get('other_reports', 0)} ta"
	)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_reports_stats_keyboard(),
		                                       parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_reports_stats_keyboard(),
		                                    parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

# ============== ANALYTICS ==============

@admin_router.callback_query(F.data == "admin_analytics")
async def show_analytics_menu(callback_query: CallbackQuery, state: FSMContext):
	"""Analitika menyusini ko'rsatish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	text = (
		"📊 **ANALITIKA VA STATISTIKA**\n\n"
		"Ko'rmoqchi bo'lgan statistika turini tanlang:"
	)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_analytics_keyboard(),
		                                       parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_analytics_keyboard(), parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.callback_query(F.data == "analytics_general")
async def show_general_analytics(callback_query: CallbackQuery, state: FSMContext):
	"""Umumiy analitikani ko'rsatish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	stats = await get_database_stats()
	
	today = date.today()
	week_ago = today - timedelta(days=7)
	month_ago = today - timedelta(days=30)
	
	week_reports = await get_reports_count_by_date(week_ago.isoformat(), today.isoformat())
	month_reports = await get_reports_count_by_date(month_ago.isoformat(), today.isoformat())
	
	# Qo'shimcha statistikalar
	all_users = await get_all_users()
	active_users = 0
	blocked_users = 0
	
	for user in all_users:
		is_blocked = await check_user_blocked(user[1])
		if is_blocked:
			blocked_users += 1
		else:
			active_users += 1
	
	text = (
		"📊 **UMUMIY ANALITIKA**\n\n"
		"👥 **FOYDALANUVCHILAR:**\n"
		f"├ Jami: {stats.get('total_users', 0)} ta\n"
		f"├ ✅ Faol: {active_users} ta\n"
		f"└ 🔒 Bloklangan: {blocked_users} ta\n\n"
		
		"📝 **HISOBOTLAR:**\n"
		f"├ Jami: {stats.get('total_reports', 0)} ta\n"
		f"├ ✅ Tasdiqlangan: {stats.get('confirmed_reports', 0)} ta\n"
		f"├ ⏳ Kutilayotgan: {stats.get('pending_reports', 0)} ta\n"
		f"└ 🎯 Tasdiqlash foizi: {stats.get('confirmation_rate', 0)}%\n\n"
		
		"📅 **VAQT BO'YICHA:**\n"
		f"├ Bugun: {stats.get('today_reports', 0)} ta\n"
		f"├ Hafta: {week_reports} ta\n"
		f"└ Oy: {month_reports} ta\n\n"
		
		"🏙️ **JOYLASHUV BO'YICHA:**\n"
		f"├ Toshkent shahar: {stats.get('tashkent_reports', 0)} ta\n"
		f"└ Boshqa hududlar: {stats.get('other_reports', 0)} ta\n\n"
		
		"🏢 **TIZIM:**\n"
		f"├ Guruhlar: {len(await get_all_telegram_groups())} ta\n"
		f"├ Google Sheets: {len(await get_all_google_sheets())} ta\n"
		f"├ Adminlar: {len(get_all_admins())} ta\n"
		f"└ Tasdiqlovchilar: {len(get_all_approvers())} ta"
	)
	
	await callback_query.message.answer(text, parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.callback_query(F.data == "analytics_daily")
async def show_daily_analytics(callback_query: CallbackQuery, state: FSMContext):
	"""Kunlik analitikani ko'rsatish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	text = "📅 **KUNLIK ANALITIKA**\n\n"
	
	# So'nggi 7 kunlik statistika
	for i in range(7):
		day = date.today() - timedelta(days=i)
		day_reports = await get_reports_count_by_date(day.isoformat())
		day_name = day.strftime('%A')[:3]  # Qisqa kun nomi
		
		if i == 0:
			day_label = "Bugun"
		elif i == 1:
			day_label = "Kecha"
		else:
			day_label = f"{day_name} ({day.strftime('%d.%m')})"
		
		# Grafik ko'rinishi
		bar = "█" * min(day_reports, 20)  # Maksimal 20 ta belgi
		
		text += f"**{day_label}:** {day_reports} ta\n"
		text += f"{bar}\n\n"
	
	# Haftalik o'rtacha
	week_total = sum(
		[await get_reports_count_by_date((date.today() - timedelta(days=i)).isoformat()) for i in range(7)])
	week_average = round(week_total / 7, 1)
	
	text += f"📊 **Haftalik o'rtacha:** {week_average} ta/kun\n"
	text += f"📈 **Haftalik jami:** {week_total} ta"
	
	await callback_query.message.answer(text, parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

# ============== SETTINGS ==============

@admin_router.callback_query(F.data == "admin_settings")
async def show_settings_menu(callback_query: CallbackQuery, state: FSMContext):
	"""Sozlamalar menyusini ko'rsatish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	try:
		await callback_query.message.edit_text(
			"⚙️ **SOZLAMALAR**\n\nKerakli bo'limni tanlang:",
			reply_markup=get_enhanced_settings_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
	except TelegramBadRequest:
		await callback_query.message.answer(
			"⚙️ **SOZLAMALAR**\n\nKerakli bo'limni tanlang:",
			reply_markup=get_enhanced_settings_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
	await callback_query.answer()

@admin_router.callback_query(F.data == "system_info")
async def show_system_info(callback_query: CallbackQuery, state: FSMContext):
	"""Tizim ma'lumotlarini ko'rsatish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	text = format_system_info()
	
	keyboard = InlineKeyboardMarkup(inline_keyboard=[
		[InlineKeyboardButton(text="🔙 Sozlamalar", callback_data="admin_settings")]
	])
	
	try:
		await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.callback_query(F.data == "database_info")
async def show_database_info(callback_query: CallbackQuery, state: FSMContext):
	"""Ma'lumotlar bazasi ma'lumotlarini ko'rsatish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	text = await format_database_info()
	
	keyboard = InlineKeyboardMarkup(inline_keyboard=[
		[InlineKeyboardButton(text="🔙 Sozlamalar", callback_data="admin_settings")]
	])
	
	try:
		await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

# ============== NAVIGATION ==============

@admin_router.callback_query(F.data == "admin_menu")
async def back_to_admin_menu(callback_query: CallbackQuery, state: FSMContext):
	"""Admin menyuga qaytish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	await state.clear()
	
	admin_type = "👑 Asosiy Admin" if callback_query.from_user.id == ADMIN_ID else "👨‍💻 Admin"
	
	try:
		await callback_query.message.edit_text(
			f"👨‍💻 **ADMIN PANEL v2.1**\n\n"
			f"Salom, {admin_type}!\n"
			f"🆔 ID: `{callback_query.from_user.id}`\n"
			f"📅 Vaqt: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
			f"Kerakli bo'limni tanlang:",
			reply_markup=get_enhanced_admin_menu_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
	except TelegramBadRequest:
		await callback_query.message.answer(
			f"👨‍💻 **ADMIN PANEL v2.1**\n\n"
			f"Salom, {admin_type}!\n"
			f"🆔 ID: `{callback_query.from_user.id}`\n"
			f"📅 Vaqt: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
			f"Kerakli bo'limni tanlang:",
			reply_markup=get_enhanced_admin_menu_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
	await callback_query.answer()

@admin_router.callback_query(F.data == "admin_exit")
async def exit_admin_panel(callback_query: CallbackQuery, state: FSMContext):
	"""Admin paneldan chiqish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	await state.clear()
	try:
		await callback_query.message.edit_text(
			"🏠 **ASOSIY MENYU**\n\nAdmin paneldan chiqildi",
			reply_markup=None,
			parse_mode=ParseMode.MARKDOWN
		)
	except TelegramBadRequest:
		await callback_query.message.answer(
			"🏠 **ASOSIY MENYU**\n\nAdmin paneldan chiqildi",
			reply_markup=None,
			parse_mode=ParseMode.MARKDOWN
		)
	
	await callback_query.message.answer(
		"Asosiy menyuga qaytdingiz.",
		reply_markup=get_main_menu_reply_keyboard()
	)
	await callback_query.answer()

@admin_router.callback_query(F.data == "cancel_admin_action")
async def cancel_admin_action_handler(callback_query: CallbackQuery, state: FSMContext):
	"""Admin amalini bekor qilish"""
	await state.clear()
	try:
		await callback_query.message.edit_text(
			"🚫 **BEKOR QILINDI**\n\nAdmin jarayoni bekor qilindi",
			reply_markup=None,
			parse_mode=ParseMode.MARKDOWN
		)
	except TelegramBadRequest:
		await callback_query.message.answer(
			"🚫 **BEKOR QILINDI**\n\nAdmin jarayoni bekor qilindi",
			reply_markup=None,
			parse_mode=ParseMode.MARKDOWN
		)
	
	await callback_query.message.answer(
		"Admin panelga qaytish uchun /rava buyrug'ini yuboring.",
		reply_markup=get_main_menu_reply_keyboard()
	)
	await callback_query.answer()

# ============== BROADCAST MESSAGING ==============

@admin_router.callback_query(F.data == "admin_broadcast")
async def start_broadcast(callback_query: CallbackQuery, state: FSMContext):
	"""Barcha foydalanuvchilarga xabar yuborish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	await state.set_state(AdminStates.waiting_for_broadcast_message)
	text = (
		"📢 **BARCHA FOYDALANUVCHILARGA XABAR**\n\n"
		"Barcha foydalanuvchilarga yubormoqchi bo'lgan xabaringizni kiriting:\n\n"
		"⚠️ **DIQQAT:**\n"
		"• Xabar barcha ro'yxatdan o'tgan foydalanuvchilarga yuboriladi\n"
		"• Bloklangan foydalanuvchilarga ham yuboriladi\n"
		"• Bu amal bekor qilib bo'lmaydi\n\n"
		"💡 Xabaringizni ehtiyotkorlik bilan yozing"
	)
	
	try:
		await callback_query.message.edit_text(text, reply_markup=get_admin_cancel_inline_keyboard(),
		                                       parse_mode=ParseMode.MARKDOWN)
	except TelegramBadRequest:
		await callback_query.message.answer(text, reply_markup=get_admin_cancel_inline_keyboard(),
		                                    parse_mode=ParseMode.MARKDOWN)
	await callback_query.answer()

@admin_router.message(AdminStates.waiting_for_broadcast_message)
async def process_broadcast_message(message: Message, state: FSMContext):
	"""Broadcast xabarini qayta ishlash"""
	if not is_admin(message.from_user.id):
		await message.answer("🚫 Ruxsat yo'q.")
		await state.clear()
		return
	
	broadcast_message = message.text.strip() if message.text else ""
	if not broadcast_message or len(broadcast_message) < 5:
		await message.answer(
			"⚠️ **XATO**\n\n"
			"Xabar kamida 5 belgi bo'lishi kerak.\n"
			"Qaytadan kiriting:",
			reply_markup=get_admin_cancel_inline_keyboard(),
			parse_mode=ParseMode.MARKDOWN
		)
		return
	
	await state.update_data(broadcast_message=broadcast_message)
	await state.set_state(AdminStates.waiting_for_broadcast_confirmation)
	
	# Foydalanuvchilar sonini olish
	all_users = await get_all_users()
	user_count = len(all_users)
	
	confirmation_text = (
		f"📢 **XABAR TASDIQLASH**\n\n"
		f"**Yuborilishi kerak bo'lgan xabar:**\n"
		f"```\n{broadcast_message}\n```\n\n"
		f"👥 **Qabul qiluvchilar:** {user_count} ta foydalanuvchi\n\n"
		f"❓ Xabarni yuborishni tasdiqlaysizmi?"
	)
	
	keyboard = InlineKeyboardMarkup(inline_keyboard=[
		[
			InlineKeyboardButton(text="✅ Yuborish", callback_data="confirm_broadcast"),
			InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_admin_action")
		]
	])
	
	await message.answer(confirmation_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

@admin_router.callback_query(F.data == "confirm_broadcast")
async def confirm_broadcast(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
	"""Broadcast xabarini tasdiqlash va yuborish"""
	if not is_admin(callback_query.from_user.id):
		await callback_query.answer("🚫 Ruxsat yo'q.", show_alert=True)
		return
	
	data = await state.get_data()
	broadcast_message = data.get("broadcast_message")
	
	if not broadcast_message:
		await callback_query.answer("❌ Xabar topilmadi!", show_alert=True)
		await state.clear()
		return
	
	# Barcha foydalanuvchilarni olish
	all_users = await get_all_users()
	
	await callback_query.message.edit_text(
		f"📤 **XABAR YUBORILMOQDA...**\n\n"
		f"Jami foydalanuvchilar: {len(all_users)} ta\n"
		f"Yuborilgan: 0 ta\n"
		f"Xatoliklar: 0 ta",
		parse_mode=ParseMode.MARKDOWN
	)
	
	sent_count = 0
	error_count = 0
	
	# Har bir foydalanuvchiga xabar yuborish
	for user in all_users:
		user_id, telegram_id, full_name, reg_date, is_blocked, group_name = user
		
		try:
			await bot.send_message(
				chat_id=telegram_id,
				text=f"📢 **ADMIN XABARI**\n\n{broadcast_message}",
				parse_mode=ParseMode.MARKDOWN
			)
			sent_count += 1
			
			# Har 10 ta xabardan keyin progress yangilash
			if sent_count % 10 == 0:
				try:
					await callback_query.message.edit_text(
						f"📤 **XABAR YUBORILMOQDA...**\n\n"
						f"Jami foydalanuvchilar: {len(all_users)} ta\n"
						f"Yuborilgan: {sent_count} ta\n"
						f"Xatoliklar: {error_count} ta",
						parse_mode=ParseMode.MARKDOWN
					)
				except:
					pass
		
		except Exception as e:
			error_count += 1
			logging.error(f"Broadcast error for user {telegram_id}: {e}")
	
	# Yakuniy natija
	final_text = (
		f"✅ **XABAR YUBORISH YAKUNLANDI**\n\n"
		f"📊 **NATIJALAR:**\n"
		f"├ Jami foydalanuvchilar: {len(all_users)} ta\n"
		f"├ ✅ Muvaffaqiyatli yuborilgan: {sent_count} ta\n"
		f"├ ❌ Xatoliklar: {error_count} ta\n"
		f"└ 📈 Muvaffaqiyat foizi: {round((sent_count / len(all_users)) * 100, 1)}%\n\n"
		f"📅 **Yuborilgan vaqt:** {datetime.now().strftime('%d.%m.%Y %H:%M')}"
	)
	
	await callback_query.message.edit_text(final_text, parse_mode=ParseMode.MARKDOWN)
	await state.clear()
	await callback_query.answer()
	
	logging.info(f"Broadcast completed by admin {callback_query.from_user.id}: {sent_count}/{len(all_users)} sent")

# ============== LOGGING ==============

logging.basicConfig(
	level=logging.INFO,
	format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logging.info("Enhanced Admin router v2.1 initialized successfully")
logging.info(f"Main admin ID: {ADMIN_ID}")
logging.info(f"Helper ID: {HELPER_ID}")
logging.info(f"Additional admins: {len(ADDITIONAL_ADMINS)}")
logging.info(f"Additional approvers: {len(APPROVERS)}")
logging.info("✅ Tasdiqlovchilar tizimi qo'shildi va to'liq ishga tayyor")
logging.info("📄 Sahifalash tizimi qo'shildi")
logging.info("🔧 To'liq admin panel funksiyalari")
logging.info("📢 Broadcast messaging qo'shildi")
logging.info("🏙️ Toshkent shahar funksiyasi qo'llab-quvvatlanadi")
logging.info("🎯 Admin paneldan qo'shilgan tasdiqlovchilar hisobotlarni tasdiqlash imkoniyatiga ega")
