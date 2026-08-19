import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput
import logging
from datetime import datetime
import texts
import storage
import time
import asyncio
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise SystemExit(
        "❌ Не найден токен бота. Создай файл .env рядом с bot.py и добавь строку:\n"
        "DISCORD_BOT_TOKEN=твой_токен"
    )

GUILD_ID = 1513600868258419008
ADMIN_ROLE_ID = 1513610796314263652
SUPREME_ROLE_ID = 1513610796314263652

APPEAL_CATEGORY_ACTIVE = 1529493586976964829
APPEAL_CATEGORY_ARCHIVE = 1539079071982424136

logging.basicConfig(
    filename="bot.log",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# Используем кастомный класс бота для синхронизации слеш-команд
class PartyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Синхронизация слеш-команд для конкретного сервера (обновляется моментально)
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        logging.info("Слеш-команды синхронизированы!")

bot = PartyBot()

# ───────────────────────────────────────────────
# Утилиты отправки красивых Embed в ЛС
# ───────────────────────────────────────────────
async def send_beautiful_dm(user: discord.User, title: str, description: str, color: discord.Color):
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text="Партия «Шишки»", icon_url=user.display_avatar.url)
    try:
        await user.send(embed=embed)
    except discord.Forbidden:
        logging.warning(f"Не удалось отправить ЛС пользователю {user}")

# ───────────────────────────────────────────────
# Обработчики ошибок View и Modal
# ───────────────────────────────────────────────
async def _send_error_to_interaction(interaction: discord.Interaction, message: str):
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass

async def _view_on_error(self, interaction: discord.Interaction, error: Exception, item):
    logging.error(f"Ошибка View {item}: {error}", exc_info=error)
    await _send_error_to_interaction(interaction, "❌ Произошла ошибка. Попробуйте позже.")

async def _modal_on_error(self, interaction: discord.Interaction, error: Exception):
    logging.error(f"Ошибка Modal: {error}", exc_info=error)
    await _send_error_to_interaction(interaction, "❌ Ошибка при отправке формы.")

View.on_error = _view_on_error
Modal.on_error = _modal_on_error

class GenericModal(Modal):
    def __init__(self, key: str, is_appeal=False):
        super().__init__(title=texts.MODALS[key]["title"])
        self.key = key
        self.is_appeal = is_appeal

        for f in texts.MODALS[key]["fields"]:
            self.add_item(TextInput(
                label=f["label"],
                placeholder=f["placeholder"],
                style=discord.TextStyle.long if f.get("long") else discord.TextStyle.short
            ))

    async def on_submit(self, interaction: discord.Interaction):
        if self.is_appeal:
            await handle_appeal(interaction, self)
        else:
            await handle_application(interaction, self)

# ───────────────────────────────────────────────
# Заявки и Отпуска
# ───────────────────────────────────────────────
async def handle_application(interaction, modal):
    num = storage.next_appeal_id()
    embed = discord.Embed(title=f"📄 Заявка/Отпуск #{num}", color=0x0a54ff)
    
    for c in modal.children:
        embed.add_field(name=c.label, value=c.value or "—", inline=False)

    embed.add_field(name="Статус", value="⏳ На рассмотрении", inline=False)
    embed.set_footer(text=datetime.now().strftime("%d.%m.%Y %H:%M"))

    view = ApplicationReviewView(interaction.user, modal.key, num)
    await interaction.channel.send(content=f"<@&{ADMIN_ROLE_ID}>", embed=embed, view=view)
    await interaction.response.send_message(f"✅ Форма **#{num}** успешно отправлена!", ephemeral=True)

    # После заявки заново отправляем мейн-панель в этот канал (КД 15 сек)
    panel_type = PANEL_TYPE_BY_KEY.get(modal.key)
    if panel_type:
        await refresh_main_panel(interaction.channel, panel_type)

class ApplicationReviewView(View):
    def __init__(self, user, key, num):
        super().__init__(timeout=None)
        self.user = user
        self.key = key
        self.num = num

class ApplicationReviewView(View):
    def __init__(self, user, key, num):
        super().__init__(timeout=None)
        self.user = user
        self.key = key
        self.num = num

    @discord.ui.button(label="✔️ Принять", style=discord.ButtonStyle.success)
    async def accept(self, interaction, button):
        if ADMIN_ROLE_ID not in [r.id for r in interaction.user.roles]:
            return await interaction.response.send_message("❌ Нет прав", ephemeral=True)

        member = interaction.guild.get_member(self.user.id)
        
        # 1. Выдача ролей (работает для LEADER, GOV, PARTY, VACATION)
        for rid in texts.MODALS[self.key]["roles"]:
            role = interaction.guild.get_role(rid)
            if role and member:
                await member.add_roles(role)

        # 2. Умная смена ника для ВСЕХ типов ролей и отпусков
        if member:
            embed = interaction.message.embeds[0]
            
            # Достаем первые два поля из формы (Имя Фамилия и Статик)
            val1 = embed.fields[0].value if len(embed.fields) > 0 else "Имя"
            val2 = embed.fields[1].value if len(embed.fields) > 1 else "Статик"
            
            # Если это отпуск, добавляем приставку "ОТПУСК | ", для остальных оставляем пустой
            prefix = f"{texts.VACATION_NICK_PREFIX} | " if self.key == "VACATION" else ""
            
            # Собираем базовый ник
            new_nick = f"{prefix}{val1} | {val2}"
            
            # Проверка лимита Discord (максимум 32 символа)
            if len(new_nick) > 32:
                name_parts = val1.split()
                # Если в имени больше одного слова (Имя и Фамилия), сокращаем имя до инициала
                if len(name_parts) >= 2:
                    short_name = f"{name_parts[0][0]}. {' '.join(name_parts[1:])}"
                    new_nick = f"{prefix}{short_name} | {val2}"
                
                # Если даже после сокращения длина превышает 32 символа, обрезаем жестко по лимиту
                if len(new_nick) > 32:
                    new_nick = new_nick[:32]
            
            try:
                await member.edit(nick=new_nick, reason=f"Заявка #{self.num} одобрена")
            except discord.Forbidden:
                logging.warning(f"Не удалось сменить ник {member} (ошибка иерархии ролей)")

        # 3. Отправка красивого уведомления в ЛС пользователю
        await send_beautiful_dm(
            self.user,
            "✅ Статус заявки обновлен",
            texts.MODALS[self.key]["accept_dm"].format(admin=interaction.user.mention),
            discord.Color.green()
        )

        # 4. Обновление сообщения в канале заявок (фиксация статуса)
        embed = interaction.message.embeds[0]
        for i, field in enumerate(embed.fields):
            if field.name == "Статус":
                embed.set_field_at(i, name="Статус", value=f"✅ Одобрено\nРассмотрел: {interaction.user.mention}", inline=False)
                break
        
        await interaction.message.edit(embed=embed, view=None)
        await interaction.response.send_message("Заявка одобрена, ник изменен.", ephemeral=True)

    @discord.ui.button(label="❌ Отклонить", style=discord.ButtonStyle.danger)
    async def reject(self, interaction, button):
        if ADMIN_ROLE_ID not in [r.id for r in interaction.user.roles]:
            return await interaction.response.send_message("❌ Нет прав", ephemeral=True)
        await interaction.response.send_modal(RejectModal(self.user, interaction.message, self.key, self.num))

class RejectModal(Modal, title="Причина отказа"):
    def __init__(self, user, msg, key, num):
        super().__init__()
        self.user = user
        self.msg = msg
        self.key = key
        self.num = num
        self.reason = TextInput(label="Причина", style=discord.TextStyle.long)
        self.add_item(self.reason)

    async def on_submit(self, interaction):
        await send_beautiful_dm(
            self.user,
            "❌ Статус заявки обновлен",
            texts.MODALS[self.key]["reject_dm"].format(admin=interaction.user.mention, reason=self.reason.value),
            discord.Color.red()
        )

        embed = self.msg.embeds[0]
        for i, field in enumerate(embed.fields):
            if field.name == "Статус":
                embed.set_field_at(i, name="Статус", value=f"❌ Отклонено\nПричина: {self.reason.value}\nРассмотрел: {interaction.user.mention}", inline=False)
                break
        await self.msg.edit(embed=embed, view=None)
        await interaction.response.send_message("Отклонено", ephemeral=True)

# ───────────────────────────────────────────────
# Обращения
# ───────────────────────────────────────────────
async def handle_appeal(interaction: discord.Interaction, modal):
    await interaction.response.defer(ephemeral=True)

    num = storage.next_appeal_id()
    guild = interaction.guild
    category = guild.get_channel(APPEAL_CATEGORY_ACTIVE)

    channel = await guild.create_text_channel(name=f"обращение-{num}", category=category)

    await channel.set_permissions(interaction.user, read_messages=True, send_messages=True)
    await channel.set_permissions(guild.default_role, read_messages=False)
    await channel.set_permissions(guild.get_role(ADMIN_ROLE_ID), read_messages=True, send_messages=True)

    embed = discord.Embed(title=f"🏛️ Обращение #{num}", color=0x0a54ff)
    for c in modal.children:
        embed.add_field(name=str(c.label), value=c.value or "—", inline=False)

    embed.add_field(name="Статус", value="⏳ Ожидает рассмотрения", inline=False)
    embed.set_footer(text=datetime.now().strftime("%d.%m.%Y %H:%M"))

    view = AppealAdminView(interaction.user, num, channel)
    await channel.send(content=f"{interaction.user.mention} <@&{ADMIN_ROLE_ID}>", embed=embed, view=view)

    await interaction.followup.send(f"✅ Обращение **#{num}** создано! Ваш канал: {channel.mention}", ephemeral=True)

    # После обращения заново отправляем мейн-панель обращений в исходный канал (КД 15 сек)
    panel_type = PANEL_TYPE_BY_KEY.get(modal.key)
    if panel_type:
        await refresh_main_panel(interaction.channel, panel_type)


class AppealRejectModal(Modal, title="Причина отказа"):
    def __init__(self, applicant, channel, num, message, curator):
        super().__init__()
        self.applicant = applicant
        self.channel = channel
        self.num = num
        self.message = message
        self.curator = curator
        self.reason = TextInput(label="Причина отказа", style=discord.TextStyle.long, required=True)
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await send_beautiful_dm(
            self.applicant,
            "❌ Ваше обращение отклонено",
            f"**Комментарий:** {self.reason.value}\n**Куратор:** {self.curator.mention}",
            discord.Color.red()
        )

        embed = self.message.embeds[0]
        for i, field in enumerate(embed.fields):
            if field.name == "Статус":
                embed.set_field_at(i, name="Статус", value="❌ Отклонено", inline=False)
                break
        await self.message.edit(embed=embed, view=None)

        archive = interaction.guild.get_channel(APPEAL_CATEGORY_ARCHIVE)
        await self.channel.edit(category=archive)
        await self.channel.set_permissions(interaction.guild.get_role(ADMIN_ROLE_ID), read_messages=True, send_messages=True)

        await interaction.response.send_message("Обращение отклонено и перенесено в архив", ephemeral=True)

class AppealResolveModal(Modal, title="Вердикт / Решение"):
    def __init__(self, applicant, channel, num, message, curator):
        super().__init__()
        self.applicant = applicant
        self.channel = channel
        self.num = num
        self.message = message
        self.curator = curator
        self.verdict = TextInput(label="Вердикт / Ответ", style=discord.TextStyle.long, required=True)
        self.add_item(self.verdict)

    async def on_submit(self, interaction: discord.Interaction):
        await send_beautiful_dm(
            self.applicant,
            "✅ Вынесено решение по обращению",
            f"**Решение:** {self.verdict.value}\n\n**Куратор:** {self.curator.mention}",
            discord.Color.green()
        )

        embed = self.message.embeds[0]
        for i, field in enumerate(embed.fields):
            if field.name == "Статус":
                embed.set_field_at(i, name="Статус", value="❄️ Принято решение", inline=False)
                break
        embed.add_field(name="Вердикт", value=self.verdict.value, inline=False)
        await self.message.edit(embed=embed, view=None)

        archive = interaction.guild.get_channel(APPEAL_CATEGORY_ARCHIVE)
        await self.channel.edit(category=archive)
        await self.channel.set_permissions(interaction.guild.get_role(ADMIN_ROLE_ID), read_messages=True, send_messages=True)

        await interaction.response.send_message("Решение зафиксировано, тикет в архиве.", ephemeral=True)


class AppealAdminView(View):
    def __init__(self, applicant, num, channel):
        super().__init__(timeout=None)
        self.applicant = applicant
        self.num = num
        self.channel = channel
        self.curator = None

    @discord.ui.button(label="💕 В производстве", style=discord.ButtonStyle.success, row=0)
    async def in_work(self, interaction: discord.Interaction, button: Button):
        if ADMIN_ROLE_ID not in [r.id for r in interaction.user.roles]:
            return await interaction.response.send_message("Нет прав", ephemeral=True)

        if self.curator:
            return await interaction.response.send_message("Обращение уже в работе", ephemeral=True)

        self.curator = interaction.user
        guild = interaction.guild
        admin_role = guild.get_role(ADMIN_ROLE_ID)

        for member in guild.members:
            if admin_role in member.roles and member != self.curator:
                await self.channel.set_permissions(member, read_messages=False, send_messages=False)

        await self.channel.set_permissions(self.curator, read_messages=True, send_messages=True)

        embed = interaction.message.embeds[0]
        embed.add_field(name="💕 Закреплено за", value=interaction.user.mention, inline=False)
        for i, field in enumerate(embed.fields):
            if field.name == "Статус":
                embed.set_field_at(i, name="Статус", value="♾️ В производстве", inline=False)
                break

        button.disabled = True
        button.style = discord.ButtonStyle.grey

        await interaction.response.defer(ephemeral=True)
        await interaction.message.edit(embed=embed, view=self)

        await send_beautiful_dm(
            self.applicant,
            "🟡 Обращение принято в работу",
            f"Ваше обращение официально взято на контроль.\n**Куратор:** {interaction.user.mention}",
            discord.Color.yellow()
        )
        await send_beautiful_dm(
            interaction.user,
            f"🟡 Вы куратор обращения #{self.num}",
            texts.APPEAL_IN_WORK_DM,
            discord.Color.blue()
        )
        await interaction.followup.send("Вы назначены куратором", ephemeral=True)

    @discord.ui.button(label="❌ Отклонить", style=discord.ButtonStyle.danger, row=1)
    async def reject(self, interaction: discord.Interaction, button: Button):
        if self.curator is None:
            return await interaction.response.send_message("Сначала возьмите в работу", ephemeral=True)
        if interaction.user != self.curator:
            return await interaction.response.send_message("Только куратор может это сделать", ephemeral=True)
        await interaction.response.send_modal(AppealRejectModal(self.applicant, self.channel, self.num, interaction.message, self.curator))

    @discord.ui.button(label="✅ Принято решение", style=discord.ButtonStyle.secondary, row=1)
    async def resolved(self, interaction: discord.Interaction, button: Button):
        if self.curator is None:
            return await interaction.response.send_message("Сначала возьмите в работу", ephemeral=True)
        if interaction.user != self.curator:
            return await interaction.response.send_message("Только куратор может завершить", ephemeral=True)
        await interaction.response.send_modal(AppealResolveModal(self.applicant, self.channel, self.num, interaction.message, self.curator))

class DelegateView(View):
    def __init__(self, old_curator, new_curator, appeal_channel):
        super().__init__(timeout=None)
        self.old_curator = old_curator
        self.new_curator = new_curator
        self.appeal_channel = appeal_channel

    async def _check_permission(self, interaction: discord.Interaction):
        guild = bot.get_guild(GUILD_ID)
        member = guild.get_member(interaction.user.id) if guild else None

        if not member:
            await interaction.response.send_message("Вас нет на сервере", ephemeral=True)
            return False
        if SUPREME_ROLE_ID not in [r.id for r in member.roles]:
            await interaction.response.send_message("Только Высший совет может это делать", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Одобрить", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: Button):
        if not await self._check_permission(interaction): return

        await self.appeal_channel.set_permissions(self.old_curator, read_messages=False, send_messages=False)
        await self.appeal_channel.set_permissions(self.new_curator, read_messages=True, send_messages=True)

        async for msg in self.appeal_channel.history(limit=10):
            if msg.embeds and msg.embeds[0].title.startswith("🏛️ Обращение #"):
                embed = msg.embeds[0]
                for i, field in enumerate(embed.fields):
                    if field.name in ("💕 Закреплено за", "Статус") and self.old_curator.mention in field.value:
                        new_value = field.value.replace(self.old_curator.mention, self.new_curator.mention)
                        embed.set_field_at(i, name=field.name, value=new_value, inline=field.inline)
                await msg.edit(embed=embed)
                break

        await send_beautiful_dm(self.old_curator, "🔄 Делегирование", f"Вы передали обращение {self.appeal_channel.mention} пользователю {self.new_curator.mention}.", discord.Color.blue())
        await send_beautiful_dm(self.new_curator, "🔄 Делегирование", f"Вам передано кураторство {self.appeal_channel.mention}.", discord.Color.green())
        await interaction.response.send_message("Делегирование одобрено", ephemeral=True)
        await interaction.message.edit(view=None)

    @discord.ui.button(label="Отклонить", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, button: Button):
        if not await self._check_permission(interaction): return
        await send_beautiful_dm(self.old_curator, "❌ Делегирование отклонено", f"Запрос на передачу {self.appeal_channel.mention} отклонен.", discord.Color.red())
        await interaction.response.send_message("Передача отклонена", ephemeral=True)
        await interaction.message.edit(view=None)

# ───────────────────────────────────────────────
# Основные панели (Views)
# ───────────────────────────────────────────────
class MainRolesView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🤝 Руководство другой партии", style=discord.ButtonStyle.primary)
    async def leader(self, i: discord.Interaction, _):
        await i.response.send_modal(GenericModal("LEADER"))

    @discord.ui.button(label="🎖️ Запрос роли госслужащего", style=discord.ButtonStyle.secondary)
    async def gov_role(self, i: discord.Interaction, _):
        await i.response.send_modal(GenericModal("GOV"))

    @discord.ui.button(label="📝 Подать заявку в партию", style=discord.ButtonStyle.success)
    async def party_apply(self, i: discord.Interaction, _):
        await i.response.send_modal(GenericModal("PARTY"))

class VacationView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="🏖️ Уйти в отпуск", style=discord.ButtonStyle.success)
    async def vacation(self, i: discord.Interaction, _):
        await i.response.send_modal(GenericModal("VACATION"))

class AppealsMainView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🗣️ Гражданское обращение", style=discord.ButtonStyle.primary)
    async def civil(self, i, _):
        await i.response.send_modal(GenericModal("CIVIL", True))

    @discord.ui.button(label="💡 Инициатива / предложение", style=discord.ButtonStyle.secondary)
    async def initiative(self, i, _):
        await i.response.send_modal(GenericModal("INITIATIVE", True))

    @discord.ui.button(label="⚖️ Жалоба", style=discord.ButtonStyle.danger)
    async def complaint(self, i, _):
        await i.response.send_modal(GenericModal("COMPLAINT", True))

    @discord.ui.button(label="🤝 Сотрудничество", style=discord.ButtonStyle.success)
    async def cooperation(self, i, _):
        await i.response.send_modal(GenericModal("COOPERATION", True))


# ───────────────────────────────────────────────
# Конфигурация мейн-панелей + автопереотправка/автовосстановление
# ───────────────────────────────────────────────
PANEL_CONFIGS = {
    "ROLES": {"text": texts.MAIN_TEXT, "view_cls": MainRolesView, "color": 0x0a54ff},
    "VACATION": {"text": texts.VACATION_MAIN_TEXT, "view_cls": VacationView, "color": 0x00FFaa},
    "APPEALS": {"text": texts.APPEALS_MAIN_TEXT, "view_cls": AppealsMainView, "color": 0x0a54ff},
}

# Какой мейн-панели соответствует ключ формы, чтобы после заявки/обращения
# переотправить именно ту панель, с которой она была подана
PANEL_TYPE_BY_KEY = {
    "LEADER": "ROLES",
    "GOV": "ROLES",
    "PARTY": "ROLES",
    "VACATION": "VACATION",
    "CIVIL": "APPEALS",
    "INITIATIVE": "APPEALS",
    "COMPLAINT": "APPEALS",
    "COOPERATION": "APPEALS",
}


async def send_main_panel(channel: discord.abc.Messageable, panel_type: str):
    """Отправляет мейн-панель указанного типа в канал и запоминает её местоположение в БД."""
    config = PANEL_CONFIGS[panel_type]
    embed = discord.Embed(description=config["text"], color=config["color"])
    embed.set_footer(text=datetime.now().strftime("%d.%m.%Y %H:%M"))
    message = await channel.send(embed=embed, view=config["view_cls"]())
    storage.save_panel_location(panel_type, channel.id, message.id)
    return message


async def refresh_main_panel(channel: discord.abc.Messageable, panel_type: str):
    """
    Заново отправляет мейн-текст панели в конец канала после заявки/обращения,
    чтобы кнопки всегда оставались снизу. КД — 15 секунд на канал, чтобы не спамить
    панелью при частых заявках подряд.
    """
    if panel_type not in PANEL_CONFIGS:
        return
    if not storage.check_panel_resend_cd(channel.id):
        return  # КД ещё не прошёл

    storage.set_panel_resend_cd(channel.id)

    # Удаляем предыдущую версию панели в этом же канале, чтобы не копилось дублей
    location = storage.get_panel_location(panel_type)
    if location and location[0] == channel.id:
        try:
            old_message = await channel.fetch_message(location[1])
            await old_message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    try:
        await send_main_panel(channel, panel_type)
    except discord.HTTPException as e:
        logging.warning(f"Не удалось переотправить панель {panel_type}: {e}")


async def restore_main_panels():
    """
    Выполняется при каждом запуске бота: проверяет сохранённые в БД мейн-панели
    и обновляет их (переустанавливает View), чтобы кнопки продолжали работать
    после перезапуска без ручной повторной отправки через /send_roles и т.д.
    """
    for panel_type, config in PANEL_CONFIGS.items():
        location = storage.get_panel_location(panel_type)
        if not location:
            continue

        channel_id, message_id = location
        channel = bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logging.warning(f"[restore_main_panels] Канал для панели {panel_type} не найден")
                continue

        try:
            message = await channel.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logging.warning(f"[restore_main_panels] Панель {panel_type} не найдена в канале — нужно отправить заново вручную")
            continue

        try:
            embed = discord.Embed(description=config["text"], color=config["color"])
            embed.set_footer(text=datetime.now().strftime("%d.%m.%Y %H:%M"))
            await message.edit(embed=embed, view=config["view_cls"]())
            logging.info(f"[restore_main_panels] Панель {panel_type} восстановлена после перезапуска")
        except discord.HTTPException as e:
            logging.warning(f"[restore_main_panels] Не удалось обновить панель {panel_type}: {e}")


@bot.event
async def on_ready():
    logging.info(f"Бот {bot.user} запущен и готов к работе!")
    await restore_main_panels()


# ───────────────────────────────────────────────
# СЛЕШ-КОМАНДЫ НА СЕРВЕРЕ (Удаляются из чата)
# ───────────────────────────────────────────────
def is_admin(interaction: discord.Interaction) -> bool:
    if isinstance(interaction.user, discord.Member):
        return ADMIN_ROLE_ID in [r.id for r in interaction.user.roles]
    return False

@bot.tree.command(name="send_roles", description="Выслать панель получения ролей")
@app_commands.default_permissions(administrator=True)
async def send_roles_slash(interaction: discord.Interaction):
    await send_main_panel(interaction.channel, "ROLES")
    await interaction.response.send_message("Панель ролей отправлена", ephemeral=True)

@bot.tree.command(name="send_vacation", description="Выслать панель для ухода в отпуск")
@app_commands.default_permissions(administrator=True)
async def send_vacation_slash(interaction: discord.Interaction):
    await send_main_panel(interaction.channel, "VACATION")
    await interaction.response.send_message("Панель отпусков отправлена", ephemeral=True)

@bot.tree.command(name="send_appeals", description="Выслать панель обращений")
@app_commands.default_permissions(administrator=True)
async def send_appeals_slash(interaction: discord.Interaction):
    await send_main_panel(interaction.channel, "APPEALS")
    await interaction.response.send_message("Панель обращений отправлена", ephemeral=True)

@bot.tree.command(name="delegate", description="Передать обращение другому куратору")
async def delegate_slash(interaction: discord.Interaction, target_member: discord.Member):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ Нет прав", ephemeral=True)

    if ADMIN_ROLE_ID not in [r.id for r in target_member.roles]:
        return await interaction.response.send_message("❌ Передавать можно только администратору", ephemeral=True)

    if not storage.check_delegate_cd(interaction.user.id):
        return await interaction.response.send_message("⏳ КД на делегирование: 5 часов", ephemeral=True)

    storage.set_delegate_cd(interaction.user.id)
    view = DelegateView(interaction.user, target_member, interaction.channel)

    success = 0
    for m in interaction.guild.members:
        if SUPREME_ROLE_ID in [r.id for r in m.roles]:
            try:
                await send_beautiful_dm(
                    m, "⚠️ Запрос на делегирование",
                    f"{interaction.user.mention} хочет передать обращение {interaction.channel.mention} ➔ {target_member.mention}\nОдобрите или отклоните ниже.",
                    discord.Color.yellow()
                )
                await m.send(view=view) # View отдельным сообщением из-за ограничений
                success += 1
            except Exception:
                pass

    await interaction.response.send_message(f"Запрос отправлен {success} членам Высшего совета.", ephemeral=True)

@bot.tree.command(name="fromvacation", description="Вернуть пользователя из отпуска")
async def fromvacation_slash(interaction: discord.Interaction, target: discord.Member):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ Нет прав", ephemeral=True)

    for rid in texts.VACATION_ROLES:
        role = interaction.guild.get_role(rid)
        if role and role in target.roles:
            await target.remove_roles(role)

    prefix = f"{texts.VACATION_NICK_PREFIX} | "
    if target.nick and target.nick.startswith(prefix):
        restored = target.nick[len(prefix):].strip()
        try:
            await target.edit(nick=restored or None)
        except discord.Forbidden:
            pass

    await interaction.response.send_message(f"✅ {target.mention} возвращён из отпуска", ephemeral=True)

# ───────────────────────────────────────────────
# Команда /gov — ИСКЛЮЧИТЕЛЬНО В ЛС
# ───────────────────────────────────────────────
class GovMessageModal(Modal, title="Рассылка от Партии «Шишки»"):
    message_text = TextInput(label="Текст", style=discord.TextStyle.long, required=True, max_length=2000)

    def __init__(self, target: str):
        super().__init__()
        self.target = target

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = bot.get_guild(GUILD_ID)
        
        tasks = []
        for member in guild.members:
            if member.bot or member == interaction.user: continue
            if self.target == "here" and member.status != discord.Status.online: continue
            
            embed = discord.Embed(
                title="📣 Рассылка от Руководства Партии «Шишки»",
                description=self.message_text.value,
                color=discord.Color.blue()
            )
            tasks.append(member.send(embed=embed))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        success = sum(1 for r in results if not isinstance(r, Exception))
        failed = len(results) - success

        await interaction.followup.send(f"✅ Готово! Отправлено: **{success}**, Ошибок ЛС: **{failed}**", ephemeral=True)

@bot.tree.command(name="gov", description="Сделать глобальную рассылку (ТОЛЬКО В ЛС)")
@app_commands.choices(target=[
    app_commands.Choice(name="Всем (everyone)", value="everyone"),
    app_commands.Choice(name="Только онлайн (here)", value="here")
])
async def gov_slash(interaction: discord.Interaction, target: str):
    if interaction.guild_id is not None:
        return await interaction.response.send_message("❌ Эта команда работает **исключительно в личных сообщениях** бота. Напишите боту в ЛС.", ephemeral=True)

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return await interaction.response.send_message("❌ Сервер партии не найден.", ephemeral=True)

    member = guild.get_member(interaction.user.id)
    if not member or SUPREME_ROLE_ID not in [r.id for r in member.roles]:
        return await interaction.response.send_message("❌ У вас нет прав Высшего совета.", ephemeral=True)

    await interaction.response.send_modal(GovMessageModal(target))
# ───────────────────────────────────────────────
# ВОССТАНОВЛЕННЫЙ ФУНКЦИОНАЛ (СТАТИСТИКА, СТАФФ, ПОИСК)
# ───────────────────────────────────────────────

# Утилита для стаффа
def build_staff_text(guild: discord.Guild, content: str) -> str:
    lines = content.split('\n')
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('> <@&'):
            try:
                role_id = int(stripped.split('<@&')[1].split('>')[0])
                role = guild.get_role(role_id)
                if role:
                    members = [m for m in role.members if not m.bot]
                    mentions = ' '.join(m.mention for m in members) if members else '**Вакантно**'
                    new_line = f"> {role.mention} — {mentions}"
                else:
                    new_line = line
            except Exception:
                new_line = line
            new_lines.append(new_line)
        else:
            new_lines.append(line)
    return '\n'.join(new_lines)

# Утилита для получения Embed (для поиска)
async def get_appeal_embed(channel: discord.TextChannel):
    async for msg in channel.history(limit=20):
        if msg.embeds:
            return msg, msg.embeds[0]
    return None, None

@bot.tree.command(name="send_staff", description="Отправить список старшего состава")
async def send_staff_slash(interaction: discord.Interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ Нет прав", ephemeral=True)
    
    template = """
## <@&1449585140257783908>
### <@&1444832400847933631>
> <@&1444832200129380575>
> <@&1444832328001126441>
> <@&1452713236200816843>
> <@&1448830461584609463>
## <@&1449585020934164520>
### <@&1448833470012067982>
> <@&1448830590874030111>
> <@&1448830738215735386>
### <@&1448833035234447441>
> <@&1448830710646571068>
> <@&1448830528122785943>
> <@&1448831567765045521>
"""
    await interaction.response.defer(ephemeral=True)
    final_text = build_staff_text(interaction.guild, template)
    await interaction.channel.send(final_text)
    await interaction.followup.send("✅ Список состава отправлен!", ephemeral=True)

@bot.tree.command(name="update_staff", description="Обновить список старшего состава в этом канале")
async def update_staff_slash(interaction: discord.Interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ Нет прав", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    async for msg in interaction.channel.history(limit=100):
        if msg.author == bot.user and msg.content.startswith("## <@&1449585140257783908>"):
            new_content = build_staff_text(interaction.guild, msg.content)
            await msg.edit(content=new_content)
            return await interaction.followup.send("✅ Список успешно обновлён!", ephemeral=True)

    await interaction.followup.send("❌ Сообщение со списком не найдено в этом канале.", ephemeral=True)

@bot.tree.command(name="status", description="Общая статистика обращений")
async def status_slash(interaction: discord.Interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ Нет прав", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    active_category = guild.get_channel(APPEAL_CATEGORY_ACTIVE)
    archive_category = guild.get_channel(APPEAL_CATEGORY_ARCHIVE)

    total = pending = in_work = rejected = resolved = 0
    curators = set()

    async def process_category(category, is_archive=False):
        nonlocal total, pending, in_work, rejected, resolved, curators
        if not category: return
        for channel in category.channels:
            if not channel.name.startswith("обращение-"): continue
            total += 1
            msg, embed = await get_appeal_embed(channel)
            if not embed: continue

            status_field = next((f for f in embed.fields if f.name == "Статус"), None)
            curator_field = next((f for f in embed.fields if f.name == "💕 Закреплено за"), None)
            status_text = status_field.value.lower() if status_field else ""

            if not is_archive:
                if "ожидает" in status_text: pending += 1
                elif "в производстве" in status_text:
                    in_work += 1
                    if curator_field:
                        for part in curator_field.value.split():
                            if part.startswith("<@"):
                                uid = part.replace("<@", "").replace(">", "").replace("!", "")
                                if uid.isdigit(): curators.add(int(uid))
            else:
                if "отклонено" in status_text: rejected += 1
                elif "принято решение" in status_text: resolved += 1

    await process_category(active_category, False)
    await process_category(archive_category, True)

    embed = discord.Embed(title="📊 Статистика обращений партии «Шишки»", color=0x0a54ff)
    embed.add_field(name="Всего", value=total, inline=True)
    embed.add_field(name="Ожидает", value=pending, inline=True)
    embed.add_field(name="В производстве", value=in_work, inline=True)
    embed.add_field(name="Отклонено", value=rejected, inline=True)
    embed.add_field(name="Принято решение", value=resolved, inline=True)
    embed.add_field(name="Активных кураторов", value=len(curators), inline=True)
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="myappeals", description="Список моих обращений как куратора")
async def myappeals_slash(interaction: discord.Interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ Нет прав", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    user_id = interaction.user.id
    appeals = []

    for category in [guild.get_channel(APPEAL_CATEGORY_ACTIVE), guild.get_channel(APPEAL_CATEGORY_ARCHIVE)]:
        if not category: continue
        for channel in category.channels:
            if not channel.name.startswith("обращение-"): continue
            msg, embed = await get_appeal_embed(channel)
            if not embed: continue

            curator_field = next((f for f in embed.fields if f.name == "💕 Закреплено за"), None)
            status_field = next((f for f in embed.fields if f.name == "Статус"), None)

            if curator_field:
                for part in curator_field.value.split():
                    if part.startswith("<@"):
                        uid = part.replace("<@", "").replace(">", "").replace("!", "")
                        if uid.isdigit() and int(uid) == user_id:
                            location = "В архиве" if category.id == APPEAL_CATEGORY_ARCHIVE else "Активно"
                            appeals.append((channel, status_field.value if status_field else "Неизвестно", location))

    if not appeals:
        return await interaction.followup.send("У вас нет обращений, где вы куратор.", ephemeral=True)

    embed = discord.Embed(title=f"📂 Ваши обращения ({len(appeals)})", color=0x0a54ff)
    for channel, status, location in appeals[:15]:
        num = channel.name.replace("обращение-", "")
        embed.add_field(name=f"Обращение #{num}", value=f"Статус: {status}\nЛокация: {location}\n[Открыть]({channel.jump_url})", inline=False)
    
    if len(appeals) > 15:
        embed.set_footer(text="Показаны первые 15 обращений")
        
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="searchappeal", description="Поиск обращений по тексту/номеру")
@app_commands.describe(query="Номер или текст для поиска (например: 29 или 'жалоба')")
async def searchappeal_slash(interaction: discord.Interaction, query: str):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ Нет прав", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    active = guild.get_channel(APPEAL_CATEGORY_ACTIVE)
    archive = guild.get_channel(APPEAL_CATEGORY_ARCHIVE)
    results = []
    query_lower = query.lower()

    for category in [active, archive]:
        if not category: continue
        for channel in category.channels:
            if not channel.name.startswith("обращение-"): continue
            if query_lower in channel.name.lower():
                results.append((channel, "По номеру канала"))
                continue
            
            msg, embed = await get_appeal_embed(channel)
            if not embed: continue
            
            for field in embed.fields:
                if field.value and query_lower in field.value.lower():
                    results.append((channel, "Найдено в тексте"))
                    break

    if not results:
        return await interaction.followup.send(f"Ничего не найдено по запросу `{query}`", ephemeral=True)

    embed = discord.Embed(title=f"Результаты поиска: {query} ({len(results)})", color=0x0a54ff)
    for channel, reason in results[:10]:
        num = channel.name.replace("обращение-", "")
        status = "Активно" if channel.category_id == APPEAL_CATEGORY_ACTIVE else "В архиве"
        embed.add_field(name=f"Обращение #{num} ({reason})", value=f"Статус: {status}\n[Открыть]({channel.jump_url})", inline=False)

    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="rnumber", description="Обнуление счётчика обращений (Высший совет)")
async def rnumber_slash(interaction: discord.Interaction):
    member = interaction.guild.get_member(interaction.user.id)
    if not member or SUPREME_ROLE_ID not in [r.id for r in member.roles]:
        return await interaction.response.send_message("❌ Только Высший совет может обнулять счётчик", ephemeral=True)

    old_counter = storage.reset_appeal_counter()
    embed = discord.Embed(title="Счётчик обращений обнулён", description="Следующее обращение будет **№1**", color=0xFF0000)
    embed.set_footer(text=f"Выполнил: {interaction.user}")
    
    # Отправляем публично в тот канал, где ввели (чтобы история осталась), но команду саму видно не будет
    await interaction.channel.send(embed=embed)
    await interaction.response.send_message("Счетчик сброшен.", ephemeral=True)
bot.run(TOKEN)