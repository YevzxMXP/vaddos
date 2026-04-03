import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import re
import random
import io
import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageOps
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
import logging
from datetime import datetime

# Configuração de Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('FutebolGeral')

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

MONGO_URL = os.getenv("MONGO_URL")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

if not MONGO_URL:
    logger.error("MONGO_URL não encontrada nas variáveis de ambiente!")
if not DISCORD_TOKEN:
    logger.error("DISCORD_TOKEN não encontrada nas variáveis de ambiente!")

# MongoDB Setup
mongo_client = AsyncIOMotorClient(MONGO_URL)
mongo_db = mongo_client.futebol_geral
mongo_profiles = mongo_db.player_profiles

MARKET_CHANNEL_ID = 1451797805847806013
PLAYER_IMAGES_CHANNEL_ID = 1451797804401037469
TRANSFER_LOG_CHANNEL_ID = 1457174466869067776

TEAM_ROLES = {
    1451797802685567073: "Corinthians",
    1451797802685567071: "São Paulo",
    1451797802685567070: "Santos",
    1451797802668527618: "Athletico Paranaense",
    1451797802668527624: "Vasco",
    1451797802685567068: "Mirassol",
    1451797802685567069: "Bragantino",
    1451797802668527617: "Bahia",
    1451797802668527623: "Botafogo",
    1451797802685567072: "Palmeiras",
    1451797802668527625: "Fluminense",
    1451797802652008606: "Vitória",
    1451797802668527616: "Ceará",
    1451797802668527619: "Internacional",
    1451797802652008608: "Juventude",
    1451797802685567067: "Flamengo",
    1451797802668527622: "Cruzeiro",
    1451797802668527621: "Atlético Mineiro",
    1451797802652008607: "Sport",
    1451797802668527620: "Grêmio",
    1451797802652008605: "Sem Clube"
}

async def save_profile_to_mongo(user_id, profile_data):
    try:
        await mongo_profiles.update_one(
            {"user_id": user_id},
            {"$set": profile_data},
            upsert=True
        )
        logger.info(f"Perfil de {user_id} salvo no MongoDB.")
    except Exception as e:
        logger.error(f"Erro ao salvar perfil no MongoDB: {e}")

async def get_profile_from_mongo(user_id):
    try:
        profile = await mongo_profiles.find_one({"user_id": user_id})
        if not profile:
            new_profile = {
                "user_id": user_id,
                "name": None,
                "position": "Indefinida",
                "club": "Sem Clube",
                "goals": 0,
                "assists": 0,
                "saves": 0,
                "tackles": 0
            }
            await save_profile_to_mongo(user_id, new_profile)
            return new_profile
        return profile
    except Exception as e:
        logger.error(f"Erro ao buscar perfil no MongoDB: {e}")
        return None

POSITIONS = [
    "Atacante", "Segundo Atacante", "Ponta Esquerda", "Ponta Direita", 
    "Meia Ofensivo", "Meio Campista", "Volante", "Lateral Esquerdo", 
    "Lateral Direito", "Zagueiro", "Goleiro"
]

NATIONALITIES = [
    "Brasil", "Alemanha", "Espanha", "Portugal", "Argentina", "França", 
    "Estados Unidos", "Rússia", "Japão", "Nigéria", "Holanda", "Suíça", 
    "Colômbia", "Inglaterra", "Uruguai", "Chile", "Itália", "Bélgica", 
    "Turquia", "México"
]

FEET = ["Perna Direita", "Perna Esquerda", "Ambidestro"]

def detect_info_from_roles(member):
    detected = {"position": "Indefinida", "nationality": "Indefinida", "foot": "Indefinida"}
    role_names = [role.name.lower() for role in member.roles]
    
    # Detecção de Posição
    for pos in POSITIONS:
        if pos.lower() in " ".join(role_names):
            detected["position"] = pos
            break
            
    # Detecção de Nacionalidade
    for nat in NATIONALITIES:
        if nat.lower() in " ".join(role_names):
            detected["nationality"] = nat
            break
            
    # Detecção de Perna
    for foot in FEET:
        if foot.lower() in " ".join(role_names):
            detected["foot"] = foot
            break
    
    # Fallback para "perna" se não achar termos específicos
    if detected["foot"] == "Indefinida":
        for name in role_names:
            if "direita" in name: detected["foot"] = "Perna Direita"
            elif "esquerda" in name: detected["foot"] = "Perna Esquerda"
            elif "ambidestro" in name or "ambi" in name: detected["foot"] = "Ambidestro"

    return detected

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.presences = True
        super().__init__(command_prefix="-", intents=intents, case_insensitive=True)

    async def on_message(self, message):
        if message.author.bot:
            return
        await self.process_commands(message)

    async def on_member_update(self, before, after):
        before_roles = set(r.id for r in before.roles)
        after_roles = set(r.id for r in after.roles)
        
        if before_roles == after_roles:
            return

        team_ids = set(TEAM_ROLES.keys())
        SEM_CLUBE_ID = 1451797802652008605
        
        old_teams = before_roles & team_ids
        new_teams = after_roles & team_ids
        
        # 1. Recebeu Sem Clube (Livre no Mercado)
        gained_sem_clube = SEM_CLUBE_ID in after_roles and SEM_CLUBE_ID not in before_roles
        
        # 2. Recebeu um novo time (que não seja o Sem Clube)
        gained_teams = (new_teams - old_teams) - {SEM_CLUBE_ID}
        
        # Filtrar times reais (excluir Sem Clube da contagem de "times reais" para origem)
        real_old_teams = old_teams - {SEM_CLUBE_ID}

        # Condições de anúncio:
        # - Ganhou cargo de Sem Clube
        # - Ou se ganhar um time real novo
        if gained_sem_clube or gained_teams:
            # Filtrar times reais para origem
            real_old_teams = old_teams - {SEM_CLUBE_ID}
            origin_id = next(iter(real_old_teams)) if real_old_teams else None
            
            if gained_sem_clube:
                dest_id = None # Livre no Mercado
            else:
                dest_id = next(iter(new_teams - {SEM_CLUBE_ID})) if (new_teams - {SEM_CLUBE_ID}) else None
                
            # CORREÇÃO CRÍTICA: Se o destino for "Sem Clube" (id 1451797802652008605),
            # o process_transfer deve receber dest_id = None para exibir "Livre no Mercado".
            if dest_id == SEM_CLUBE_ID:
                dest_id = None

            # Evitar anúncio se a origem for Livre no Mercado e o destino também for Livre no Mercado
            if origin_id is None and dest_id is None:
                return
            if origin_id == SEM_CLUBE_ID and dest_id is None:
                return

            await self.process_transfer(after, origin_id, dest_id)

    async def process_transfer(self, member, origin_id, dest_id):
        channel = self.get_channel(TRANSFER_LOG_CHANNEL_ID)
        if not channel or not isinstance(channel, (discord.TextChannel, discord.Thread)):
            logger.error(f"Canal de transferência {TRANSFER_LOG_CHANNEL_ID} não encontrado ou inválido.")
            return

        origin_name = TEAM_ROLES.get(origin_id, "Livre no Mercado")
        dest_name = TEAM_ROLES.get(dest_id, "Livre no Mercado")
        
        # Get team role icons
        origin_icon_url = None
        dest_icon_url = None
        
        # Special case for "Livre no Mercado" emoji
        desemprego_emoji_url = "https://cdn.discordapp.com/emojis/1452850499404566528.png"
        
        guild = member.guild
        if origin_id:
            role = guild.get_role(origin_id)
            if role and role.display_icon:
                origin_icon_url = role.display_icon.url
        else:
            origin_icon_url = desemprego_emoji_url
        
        if dest_id:
            role = guild.get_role(dest_id)
            if role and role.display_icon:
                dest_icon_url = role.display_icon.url
        else:
            dest_icon_url = desemprego_emoji_url

        # Update DB club
        profile = await get_profile_from_mongo(member.id)
        if profile:
            profile["club"] = dest_name
            await save_profile_to_mongo(member.id, profile)
        
        # Fetch name from ficha channel
        player_real_name = await self.fetch_name_from_ficha(member)
        # Fetch market value from market channel (R$ format)
        market_val_rs = await self.fetch_market_value_rs(member)
        
        # Detecção automática de Posição, Nacionalidade e Perna
        auto_info = detect_info_from_roles(member)
        
        # Fetch player image from specific channel
        player_img_url = await self.fetch_last_player_image(member)
        
        # Get skills for the embed
        skills, fintas = get_skills_and_skills_fintas(member)
        
        # Generate Graphic
        graphic = await self.generate_transfer_graphic(member, origin_name, dest_name, market_val_rs, player_img_url, origin_icon_url, dest_icon_url, player_real_name)
        
        channel = self.get_channel(TRANSFER_LOG_CHANNEL_ID)
        if channel:
            # Find emojis for the teams
            origin_emoji = ""
            dest_emoji = ""
            for emoji in guild.emojis:
                if emoji.name.lower() in origin_name.lower():
                    origin_emoji = str(emoji)
                if emoji.name.lower() in dest_name.lower():
                    dest_emoji = str(emoji)
            
            if not origin_emoji and not origin_id: origin_emoji = "<:desemprego:1452850499404566528>"
            if not dest_emoji and not dest_id: dest_emoji = "<:desemprego:1452850499404566528>"

            embed = discord.Embed(
                title="🚨 TRANSFERÊNCIA CONFIRMADA",
                description=(
                    f"**Jogador:** {member.mention} ({player_real_name})\n"
                    f"**Posição:** `{auto_info['position']}`\n"
                    f"**Nacionalidade:** `{auto_info['nationality']}`\n"
                    f"**Perna:** `{auto_info['foot']}`\n"
                    f"**Habilidades:**\n"
                    f"🔹 **Comum:** {skills['comum']}\n"
                    f"🔹 **Rara:** {skills['rara']}\n"
                    f"🔹 **Épica:** {skills['epica']}\n"
                    f"🔹 **Sorteio:** {skills['sorteio']}\n\n"
                    f"**De:** {origin_emoji} {origin_name}\n"
                    f"**Para:** {dest_emoji} {dest_name}\n\n"
                    f"💰 **Valor de Mercado:** `{market_val_rs}`"
                ),
                color=discord.Color.blue()
            )
            embed.set_image(url=f"attachment://transfer_{member.id}.png")
            
            file = discord.File(fp=graphic, filename=f"transfer_{member.id}.png")
            await channel.send(embed=embed, file=file)

    async def fetch_name_from_ficha(self, member):
        return member.name

    async def fetch_market_value_rs(self, member):
        # Agora o valor é calculado dinamicamente baseado em habilidades e rolls
        profile = await get_profile_from_mongo(member.id)
        if not profile:
            return "R$ 0"
        _, market_val = await calculate_overall_and_value(profile, member)
        return market_val

    async def fetch_last_player_image(self, member):
        channel = self.get_channel(PLAYER_IMAGES_CHANNEL_ID)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return member.display_avatar.url
        
        # Comprehensive scan for member's appearance
        try:
            async for msg in channel.history(limit=500):
                # Check for messages from the member themselves with attachments
                if msg.author.id == member.id and msg.attachments:
                    for att in msg.attachments:
                        if any(att.filename.lower().endswith(ext) for ext in ['png', 'jpg', 'jpeg', 'webp']):
                            return att.url
                
                # Check for messages where the member is mentioned OR their ID is present (with attachments)
                if (member.mention in msg.content or str(member.id) in msg.content) and msg.attachments:
                    for att in msg.attachments:
                        if any(att.filename.lower().endswith(ext) for ext in ['png', 'jpg', 'jpeg', 'webp']):
                            return att.url
        except Exception:
            pass
                        
        return member.display_avatar.url

    async def generate_transfer_graphic(self, member, origin, dest, value, player_img_url, origin_icon_url=None, dest_icon_url=None, player_real_name=None):
        # 1. Padronização do Canvas (1280x720)
        width, height = 1280, 720
        img = Image.new('RGB', (width, height), color=(5, 5, 10))
        draw = ImageDraw.Draw(img)
        
        # Margens e Configurações de Layout
        margin = 60
        column_split = 580 # Lado esquerdo para o jogador
        
        # Fontes (DejaVu Sans Bold para suporte a Unicode completo, acentos e caracteres especiais)
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        try:
            font_title = ImageFont.truetype(font_path, 45)  
            font_player = ImageFont.truetype(font_path, 45) 
            font_label = ImageFont.truetype(font_path, 32)  
            font_team = ImageFont.truetype(font_path, 42)   
            font_value = ImageFont.truetype(font_path, 35)  
            font_footer = ImageFont.truetype(font_path, 22) 
        except Exception as e:
            print(f"Erro ao carregar fontes DejaVu: {e}")
            font_title = font_player = font_label = font_team = font_value = font_footer = ImageFont.load_default()

        # 2. Lado Esquerdo: Imagem do Jogador (Hero Section)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(player_img_url) as resp:
                    if resp.status == 200:
                        p_img_data = io.BytesIO(await resp.read())
                        p_img = Image.open(p_img_data).convert("RGBA")
                        
                        # Fit Image (Mantendo proporção e preenchendo)
                        p_img = ImageOps.fit(p_img, (column_split, height))
                        img.paste(p_img, (0, 0), p_img)
                        
                        # Overlay sutil para integração
                        overlay = Image.new('RGBA', (column_split, height), (0, 0, 0, 60))
                        img.paste(overlay, (0, 0), overlay)
        except Exception as e:
            print(f"Erro ao processar imagem do jogador: {e}")

        # Divisor Estilizado
        draw.rectangle((column_split - 2, 0, column_split + 4, height), fill=(0, 200, 255))

        # 3. Lado Direito: Informações e Hierarquia Visual
        right_start_x = column_split + margin
        right_center_x = column_split + (width - column_split) // 2

        # Título Superior
        title_text = "MERCADO DA BOLA"
        draw.text((right_center_x, 60), title_text, fill=(0, 200, 255), font=font_title, anchor="mt")

        # Nome do Jogador (Destaque Principal - Usando nome da ficha)
        display_name = (player_real_name or member.display_name).upper()
        draw.text((right_start_x, 160), display_name, fill="white", font=font_player)
        draw.line([(right_start_x, 250), (width - margin, 250)], fill=(60, 60, 80), width=3)

        # Seção de Clubes (DE -> PARA)
        shield_size = 140
        y_origin = 300
        y_dest = 480

        # Clube de Origem
        if origin_icon_url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(origin_icon_url) as resp:
                        if resp.status == 200:
                            s_img = Image.open(io.BytesIO(await resp.read())).convert("RGBA")
                            s_img = s_img.resize((shield_size, shield_size), Image.Resampling.LANCZOS)
                            img.paste(s_img, (right_start_x, y_origin), s_img)
            except: pass
        
        draw.text((right_start_x + shield_size + 30, y_origin + 30), "DE:", fill=(255, 100, 100), font=font_label)
        draw.text((right_start_x + shield_size + 30, y_origin + 70), origin.upper(), fill="white", font=font_team)

        # Seta de Transferência
        draw.text((right_start_x + shield_size // 2, y_origin + shield_size + 10), "▼", fill=(0, 200, 255), font=font_label, anchor="mt")

        # Clube de Destino
        if dest_icon_url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(dest_icon_url) as resp:
                        if resp.status == 200:
                            s_img = Image.open(io.BytesIO(await resp.read())).convert("RGBA")
                            s_img = s_img.resize((shield_size, shield_size), Image.Resampling.LANCZOS)
                            img.paste(s_img, (right_start_x, y_dest), s_img)
            except: pass

        draw.text((right_start_x + shield_size + 30, y_dest + 30), "PARA:", fill=(100, 255, 100), font=font_label)
        draw.text((right_start_x + shield_size + 30, y_dest + 70), dest.upper(), fill="white", font=font_team)

        # Valor Estimado (Sempre em R$)
        draw.text((right_start_x, 650), value.upper(), fill=(255, 215, 0), font=font_value)

        output = io.BytesIO()
        img.save(output, format='PNG')
        output.seek(0)
        return output

    async def setup_hook(self):
        # We sync only when a specific command is called or manually,
        # to avoid 429 during every startup.
        print(f"Bot {self.user} iniciado. Use -sync (dono) para sincronizar comandos se necessário.")

bot = MyBot()

@bot.command(name="sync")
@commands.is_owner()
async def sync_commands(ctx):
    print(f"Sincronizando comandos para {bot.user}...")
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"Comandos sincronizados: {len(synced)}")
    except Exception as e:
        await ctx.send(f"Erro ao sincronizar comandos: {e}")

@bot.event
async def on_ready():
    print(f"Bot logado como {bot.user}")
    print("O bot está pronto para receber comandos.")

async def fetch_market_value(user):
    channel = bot.get_channel(MARKET_CHANNEL_ID)
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return "€ 0"
    
    try:
        async for message in channel.history(limit=100):
            if user.mention in message.content or str(user.id) in message.content:
                # Tenta extrair valor monetário
                match = re.search(r'(?:€|R\$|USD)\s?([\d\.,]+(?:k|M|m|B|b)?)', message.content)
                if match:
                    return match.group(0)
    except Exception:
        pass
    return "€ 0"

def get_skills_and_skills_fintas(member):
    skills = {"comum": "Nenhuma", "rara": "Nenhuma", "epica": "Nenhuma", "sorteio": "Nenhuma"}
    fintas = "Nenhuma"
    for role in member.roles:
        role_name = role.name.lower()
        if "comum" in role_name: skills["comum"] = role.name
        elif "rara" in role_name: skills["rara"] = role.name
        elif "épica" in role_name or "epica" in role_name: skills["epica"] = role.name
        elif "sorteio" in role_name: skills["sorteio"] = role.name
        
        # Detecção de Fintas
        if "5 estrelas" in role_name:
            fintas = "⊂⊃﹒⭐ ✧﹒5 Estrelas﹒⇆﹒"
        elif "4 estrelas" in role_name and fintas == "Nenhuma":
            fintas = "⊂⊃﹒⭐ ✧﹒4 Estrelas﹒☠️﹒"
        elif "3 estrelas" in role_name and fintas == "Nenhuma":
            fintas = "⊂⊃﹒⭐ ✧﹒3 Estrelas﹒⇆﹒"
            
    return skills, fintas

# --- PERFIL ---
@bot.command(name="perfil")
async def perfil(ctx, member: discord.Member = None):
    member = member or (ctx.author if isinstance(ctx.author, discord.Member) else None)
    if not member:
        return await ctx.reply("Não foi possível identificar o usuário.")
    
    profile = await get_profile_from_mongo(member.id)
    skills, fintas = get_skills_and_skills_fintas(member)
    
    # Detecção automática de Posição, Nacionalidade e Perna
    auto_info = detect_info_from_roles(member)
    
    if profile is None:
        profile = {
            "user_id": member.id,
            "name": member.name,
            "position": auto_info["position"],
            "nationality": auto_info["nationality"],
            "club": "Sem Clube",
            "goals": 0,
            "assists": 0,
            "saves": 0,
            "tackles": 0
        }

    updated = False
    if auto_info["position"] != "Indefinida" and profile.get('position') in ["Indefinida", None]:
        profile['position'] = auto_info["position"]
        updated = True
        
    if auto_info["nationality"] != "Indefinida" and profile.get('nationality') in ["Indefinida", None]:
        profile['nationality'] = auto_info["nationality"]
        updated = True
        
    if auto_info["foot"] != "Indefinida" and profile.get('strong_foot') in ["Indefinida", "?", None]:
        profile['strong_foot'] = auto_info["foot"]
        updated = True
        
    if updated:
        await save_profile_to_mongo(member.id, profile)
    
    display_pos = profile.get('position')
    display_foot = profile.get('strong_foot')
    display_nat = profile.get('nationality')

    # Detecção automática de Time
    team_name = "Sem Clube"
    for role_id, t_name in TEAM_ROLES.items():
        if member.get_role(role_id):
            team_name = t_name
            break

    # Dynamic Overall and Value
    overall, market_val = await calculate_overall_and_value(profile, member)

    embed = discord.Embed(title=f"👤 {profile.get('name') or member.name}", color=discord.Color.dark_grey())
    embed.description = profile.get('bio') or "Sem biografia."
    
    # Banner do servidor como imagem grande e Avatar como thumbnail
    if member.guild.banner:
        embed.set_image(url=member.guild.banner.url)
    elif profile.get('skin_url'): 
        embed.set_image(url=profile['skin_url'])
        
    embed.set_thumbnail(url=member.display_avatar.url)

    embed.add_field(name="📋 Info", value=f"**Nome:** {profile.get('name') or member.name}\n**Posição:** {display_pos}\n**Time:** {team_name}\n**Nacionalidade:** {display_nat}\n**Perna:** {display_foot}", inline=True)
    embed.add_field(name="📊 Status", value=f"**Overall:** {overall}\n**Valor:** {market_val}\n**Gols:** {profile.get('goals', 0)}\n**Assists:** {profile.get('assists', 0)}\n**Defesas:** {profile.get('saves', 0)}\n**Desarmes:** {profile.get('tackles', 0)}", inline=True)
    
    # Habilidades sem molde do cargo (apenas nome e raridade)
    def clean_skill(skill_name, rarity):
        if not skill_name or skill_name == "Nenhuma":
            return "Nenhuma"
        # Remove a raridade do nome se ela estiver lá para não repetir
        name = skill_name.replace(rarity, "").replace(rarity.capitalize(), "").replace("Épica", "").replace("épica", "").strip()
        if not name: name = skill_name
        return f"{name} ({rarity.capitalize()})"

    skill_text = (
        f"🔹 {clean_skill(skills['comum'], 'comum')}\n"
        f"🔹 {clean_skill(skills['rara'], 'rara')}\n"
        f"🔹 {clean_skill(skills['epica'], 'épica')}\n"
        f"🔹 {clean_skill(skills['sorteio'], 'sorteio')}"
    )
    embed.add_field(name="✨ Habilidades", value=skill_text, inline=False)
    
    # Adicionando Fintas detectadas
    embed.add_field(name="✨ Fintas", value=fintas, inline=False)
    
    embed.set_footer(text=f"ID: {member.id} | Dica: use -editar ou -stats")
    await ctx.reply(embed=embed)

# --- EDITAR PERFIL ---
class EditProfileSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Dados Básicos", value="basic", description="Nome, Posição, Time, Perna Forte"),
            discord.SelectOption(label="Bio & Bio", value="bio", description="História do personagem"),
            discord.SelectOption(label="Imagens", value="images", description="Skin e Thumbnail"),
        ]
        super().__init__(placeholder="O que deseja editar?", options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "basic":
            await interaction.response.send_modal(BasicInfoModal())
        elif self.values[0] == "bio":
            await interaction.response.send_modal(BioEditModal())
        elif self.values[0] == "images":
            await interaction.response.send_modal(ImagesModal())

class BasicInfoModal(discord.ui.Modal):
    def __init__(self, *args, **kwargs):
        super().__init__(title="Dados Básicos", *args, **kwargs)
    
    name = discord.ui.TextInput(label="Nome", required=True)
    pos = discord.ui.TextInput(label="Posição", required=True)
    club = discord.ui.TextInput(label="Time Atual", required=True)
    foot = discord.ui.TextInput(label="Perna Forte", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        profile = await get_profile_from_mongo(interaction.user.id)
        if profile:
            profile["name"] = self.name.value
            profile["position"] = self.pos.value
            profile["club"] = self.club.value
            profile["strong_foot"] = self.foot.value
            await save_profile_to_mongo(interaction.user.id, profile)
            await interaction.response.send_message("Dados atualizados!", ephemeral=True)
        else:
            await interaction.response.send_message("Erro ao carregar perfil.", ephemeral=True)

class BioEditModal(discord.ui.Modal):
    def __init__(self, *args, **kwargs):
        super().__init__(title="Editar Biografia", *args, **kwargs)
    
    bio = discord.ui.TextInput(label="Biografia", style=discord.TextStyle.long, required=True)
    async def on_submit(self, interaction: discord.Interaction):
        profile = await get_profile_from_mongo(interaction.user.id)
        if profile and self.bio.value:
            profile["bio"] = self.bio.value
            await save_profile_to_mongo(interaction.user.id, profile)
        if not interaction.response.is_done():
            await interaction.response.send_message("Bio atualizada!", ephemeral=True)

class ImagesModal(discord.ui.Modal):
    def __init__(self, *args, **kwargs):
        super().__init__(title="Editar Imagens", *args, **kwargs)
    
    skin = discord.ui.TextInput(label="URL da Skin (Corpo)", required=False)
    thumb = discord.ui.TextInput(label="URL da Thumbnail (Pequena)", required=False)
    async def on_submit(self, interaction: discord.Interaction):
        profile = await get_profile_from_mongo(interaction.user.id)
        if profile:
            if self.skin.value:
                profile["skin_url"] = self.skin.value
            if self.thumb.value:
                profile["thumbnail_url"] = self.thumb.value
            await save_profile_to_mongo(interaction.user.id, profile)
        if not interaction.response.is_done():
            await interaction.response.send_message("Imagens atualizadas!", ephemeral=True)

@bot.command(name="editarperfil", aliases=["editar"])
async def editarperfil(ctx):
    view = discord.ui.View()
    view.add_item(EditProfileSelect())
    await ctx.reply("Escolha uma categoria para editar seu perfil:", view=view)

# --- ROLLS ---
import random

# ... existing imports ...

async def calculate_overall_and_value(profile, member):
    # Base attributes sum (rolls)
    attr_cols = [
        'fin_chute', 'fin_colocado', 'fin_chance',
        'ctrl_dominio', 'ctrl_disputa', 'ctrl_dribles',
        'def_bloqueio', 'def_desarme', 'pas_precisao', 'pas_lateral',
        'aer_cabeceio', 'vel_corrida', 'bpar_escanteio', 'bpar_faltas',
        'bpar_penaltis', 'gk_defesa', 'gk_penalti', 'gk_lancamento', 'gk_avancar'
    ]
    
    # Encontrar o maior roll
    max_roll = 0
    total_attrs = 0
    for col in attr_cols:
        val = profile.get(col, 13)
        total_attrs += val
        if val > max_roll:
            max_roll = val
            
    avg_attr = total_attrs / len(attr_cols)
    
    # Skills bonus e lógica de valor baseada em raridade
    skills, _ = get_skills_and_skills_fintas(member)
    
    # Preços base por raridade de habilidade (conforme exemplo do usuário)
    # Sorteio: 22, Épica: 21, Rara: 20, Comum: 19, Sem: 15
    skill_values = {
        'sorteio': 22_000_000,
        'épica': 21_000_000,
        'rara': 20_000_000,
        'comum': 19_000_000,
        'nenhuma': 15_000_000
    }
    
    highest_rarity = 'nenhuma'
    if skills['sorteio'] != "Nenhuma": highest_rarity = 'sorteio'
    elif skills['epica'] != "Nenhuma": highest_rarity = 'épica'
    elif skills['rara'] != "Nenhuma": highest_rarity = 'rara'
    elif skills['comum'] != "Nenhuma": highest_rarity = 'comum'
    
    base_price = skill_values[highest_rarity]
    
    # Multiplicador baseado no maior Roll
    # Quanto maior o roll, mais valorizado. 
    # Usaremos o max_roll como um multiplicador de bônus
    # Se o roll padrão é 13, cada ponto acima de 13 aumenta o valor em 5%
    roll_bonus = 1.0 + (max_roll - 13) * 0.05 if max_roll > 13 else 1.0
    
    # Bônus por equilíbrio (se a média for alta, o valor aumenta)
    balance_bonus = 1.0 + (avg_attr - 13) * 0.02 if avg_attr > 13 else 1.0
    
    final_price = int(base_price * roll_bonus * balance_bonus)
    
    # Overall calculation (mantendo a lógica de bônus para o número do overall)
    skill_bonus = 0
    if highest_rarity == 'sorteio': skill_bonus = 15
    elif highest_rarity == 'épica': skill_bonus = 10
    elif highest_rarity == 'rara': skill_bonus = 5
    elif highest_rarity == 'comum': skill_bonus = 2
    
    overall = int(avg_attr + skill_bonus)
    
    # Format value em Reais (R$)
    if final_price >= 1000000:
        formatted_value = f"R$ {final_price/1000000:.1f}M"
    else:
        formatted_value = f"R$ {final_price/1000:.0f}k"
        
    return overall, formatted_value

async def get_rolls_embed(profile, member):
    content = (
        f"━━━━━━━━「★」━━━━━━━━\n\n"
        f"`.     ﹏     ☰ 𝄒     .      ⏳ Todos os atributos iniciam em 13.`\n\n"
        f"╭・`Finalização`**\n"
        f"│ 🎯 Chute: {profile.get('fin_chute', 13)}\n"
        f"│ 🧠 Chute Colocado: {profile.get('fin_colocado', 13)}\n"
        f"│ 🧠 Chance Final: {profile.get('fin_chance', 13)}**\n\n"
        f"╭・`Controle de Bola`**\n"
        f"│ 🎮 Domínio: {profile.get('ctrl_dominio', 13)}\n"
        f"│ 🥷 Disputa: {profile.get('ctrl_disputa', 13)}\n"
        f"│ 🎩 Dribles: {profile.get('ctrl_dribles', 13)}**\n\n"
        f"╭・`Defesa`**\n"
        f"│ 🧱 Bloqueio: {profile.get('def_bloqueio', 13)}\n"
        f"│ 🔓 Desarme: {profile.get('def_desarme', 13)}**\n\n"
        f"╭・`Passes`**\n"
        f"│ 🎯 Precisão de Passe: {profile.get('pas_precisao', 13)}\n"
        f"│ 📤 Lateral: {profile.get('pas_lateral', 13)}**\n\n"
        f"╭・`Jogo Aéreo`**\n"
        f"│ 🤜 Cabeceio: {profile.get('aer_cabeceio', 13)}**\n\n"
        f"╭・`Velocidade`**\n"
        f"│ 🏃 Corrida: {profile.get('vel_corrida', 13)}**\n\n"
        f"╭・`Bola Parada`**\n"
        f"│ 🚩 Escanteio: {profile.get('bpar_escanteio', 13)}\n"
        f"│ 🌀 Bater Faltas: {profile.get('bpar_faltas', 13)}\n"
        f"│ ⚽ Bater Pênaltis: {profile.get('bpar_penaltis', 13)}**\n\n"
        f"╭・`Goleiro`**\n"
        f"│ 🧤 Defesa-GK: {profile.get('gk_defesa', 13)}\n"
        f"│ 🚫 Defesa de Pênalti: {profile.get('gk_penalti', 13)}\n"
        f"│ 📦 Lançamento: {profile.get('gk_lancamento', 13)}\n"
        f"│ ⚔️ Avançar: {profile.get('gk_avancar', 13)}**\n\n"
        f"`Benefícios utilizados (cite habilidades que você tem e como pegou):`\n- {profile.get('beneficios') or 'Nenhum'}\n\n"
        f"`Treinos realizados (quantidade):`\n- {profile.get('treinos', 0)}\n\n"
        f"๑‧˚₊·꒷꒷꒦︶︶꒦꒷︶︶꒦꒷︶︶︶꒷︶꒷꒦︶︶︶๑"
    )
    
    embed = discord.Embed(description=content, color=discord.Color.blue())
    
    # ALWAYS pick a random member with a banner for Rolls
    banner_url = None
    try:
        # Get all members with banner intent and presences
        guild_members = member.guild.members
        members_with_banners = [m for m in guild_members if m.banner]
        
        if members_with_banners:
            # Shuffle to ensure randomness every time the command is called
            random.shuffle(members_with_banners)
            random_member = members_with_banners[0]
            banner_url = random_member.banner.url
        elif member.guild.banner:
            banner_url = member.guild.banner.url
    except Exception as e:
        print(f"Erro ao buscar banner aleatório: {e}")
            
    if banner_url:
        embed.set_image(url=banner_url)
    
    # Thumbnail is ALWAYS user avatar
    embed.set_thumbnail(url=member.display_avatar.url)
    # Banner of the server as background (if any)
    if member.guild.banner:
        embed.set_image(url=member.guild.banner.url)
    return embed

class RollsView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label="Editar Rolls", style=discord.ButtonStyle.primary)
    async def edit_rolls(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Você só pode editar seus próprios rolls.", ephemeral=True)
        
        edit_view = RollsEditAreaView(self.user_id)
        await interaction.response.send_message("Escolha a área que deseja editar:", view=edit_view, ephemeral=True)

    @discord.ui.button(label="Editar Treino/Buff", style=discord.ButtonStyle.secondary)
    async def edit_training(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Você só pode editar seus próprios treinos.", ephemeral=True)
        await interaction.response.send_modal(TrainingBuffModal())

class TrainingBuffModal(discord.ui.Modal, title="Editar Treino/Buff"):
    beneficios = discord.ui.TextInput(label="Benefícios Utilizados", style=discord.TextStyle.long, required=False)
    treinos = discord.ui.TextInput(label="Quantidade de Treinos", placeholder="Ex: 5", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        profile = await get_profile_from_mongo(interaction.user.id)
        if profile:
            if self.beneficios.value:
                profile["beneficios"] = self.beneficios.value
            if self.treinos.value:
                profile["treinos"] = int(self.treinos.value) if self.treinos.value.isdigit() else 0
                
            await save_profile_to_mongo(interaction.user.id, profile)
            
            embed = await get_rolls_embed(profile, interaction.user)
            await interaction.response.edit_message(embed=embed)
        else:
            await interaction.response.send_message("Erro ao carregar perfil.", ephemeral=True)

class StatsModal(discord.ui.Modal, title="Editar Estatísticas"):
    goals = discord.ui.TextInput(label="Gols", placeholder="Ex: 10", required=False)
    assists = discord.ui.TextInput(label="Assistências", placeholder="Ex: 5", required=False)
    saves = discord.ui.TextInput(label="Defesas-GK", placeholder="Ex: 2", required=False)
    tackles = discord.ui.TextInput(label="Desarmes", placeholder="Ex: 8", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        profile = await get_profile_from_mongo(interaction.user.id)
        if not profile:
            await interaction.response.send_message("Erro ao carregar perfil.", ephemeral=True)
            return

        fields = {
            "goals": self.goals.value,
            "assists": self.assists.value,
            "saves": self.saves.value,
            "tackles": self.tackles.value
        }
        
        updated = False
        for field, value in fields.items():
            if value:
                profile[field] = int(value) if value.isdigit() else 0
                updated = True
            
        if not updated:
            await interaction.response.send_message("Nada para atualizar.", ephemeral=True)
            return
            
        await save_profile_to_mongo(interaction.user.id, profile)
        await interaction.response.send_message("Estatísticas atualizadas!", ephemeral=True)

@bot.command(name="stats")
async def stats(ctx):
    await ctx.reply("Abra o menu para editar suas estatísticas:", view=StatsView(), ephemeral=True)

class StatsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Editar Stats", style=discord.ButtonStyle.primary)
    async def edit_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StatsModal())

class RollsEditAreaView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=60)
        self.user_id = user_id
        
        options = [
            discord.SelectOption(label="Finalização", value="fin"),
            discord.SelectOption(label="Controle de Bola", value="ctrl"),
            discord.SelectOption(label="Defesa", value="def"),
            discord.SelectOption(label="Passes", value="pas"),
            discord.SelectOption(label="Jogo Aéreo & Velocidade", value="aer_vel"),
            discord.SelectOption(label="Bola Parada", value="bpar"),
            discord.SelectOption(label="Goleiro", value="gk"),
        ]
        self.add_item(RollsAreaSelect(options))

class RollsAreaSelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(placeholder="Selecione a área para editar...", options=options)

    async def callback(self, interaction: discord.Interaction):
        area = self.values[0]
        await interaction.response.send_modal(RollsDetailedModal(area))

class RollsDetailedModal(discord.ui.Modal):
    def __init__(self, area):
        super().__init__(title=f"Editando {area.upper()}")
        self.area = area
        self.fields = {}
        
        if area == "fin":
            self.add_field("fin_chute", "Chute", "13")
            self.add_field("fin_colocado", "Chute Colocado", "13")
            self.add_field("fin_chance", "Chance Final", "13")
        elif area == "ctrl":
            self.add_field("ctrl_dominio", "Domínio", "13")
            self.add_field("ctrl_disputa", "Disputa", "13")
            self.add_field("ctrl_dribles", "Dribles", "13")
        elif area == "def":
            self.add_field("def_bloqueio", "Bloqueio", "13")
            self.add_field("def_desarme", "Desarme", "13")
        elif area == "pas":
            self.add_field("pas_precisao", "Precisão de Passe", "13")
            self.add_field("pas_lateral", "Lateral", "13")
        elif area == "aer_vel":
            self.add_field("aer_cabeceio", "Cabeceio", "13")
            self.add_field("vel_corrida", "Corrida", "13")
        elif area == "bpar":
            self.add_field("bpar_escanteio", "Escanteio", "13")
            self.add_field("bpar_faltas", "Bater Faltas", "13")
            self.add_field("bpar_penaltis", "Bater Pênaltis", "13")
        elif area == "gk":
            self.add_field("gk_defesa", "Defesa-GK", "13")
            self.add_field("gk_penalti", "Defesa de Pênalti", "13")
            self.add_field("gk_lancamento", "Lançamento", "13")
            self.add_item(discord.ui.TextInput(label="Avançar", custom_id="gk_avancar", placeholder="13"))

    def add_field(self, db_col, label, placeholder):
        text_input = discord.ui.TextInput(label=label, custom_id=db_col, placeholder=placeholder, required=False)
        self.add_item(text_input)

    async def on_submit(self, interaction: discord.Interaction):
        profile = await get_profile_from_mongo(interaction.user.id)
        if not profile:
            await interaction.response.send_message("Erro ao carregar perfil.", ephemeral=True)
            return

        updated = False
        for item in self.children:
            if isinstance(item, discord.ui.TextInput) and item.value:
                profile[item.custom_id] = int(item.value) if item.value.isdigit() else 13
                updated = True
        
        if not updated:
            await interaction.response.send_message("Nenhum valor alterado.", ephemeral=True)
            return
            
        await save_profile_to_mongo(interaction.user.id, profile)
        
        embed = await get_rolls_embed(profile, interaction.user)
        await interaction.response.edit_message(embed=embed)

@bot.command(name="rolls")
async def rolls(ctx, member: discord.Member = None):
    if ctx.channel.id != 1451797804648497186:
        return await ctx.send("Este comando só pode ser usado no canal de rolls: <#1451797804648497186>.", delete_after=10)
    
    member = member or (ctx.author if isinstance(ctx.author, discord.Member) else None)
    if not member:
        return await ctx.reply("Não foi possível identificar o usuário.")
        
    profile = await get_profile_from_mongo(member.id)
    view = RollsView(member.id)
    await ctx.reply(embed=await get_rolls_embed(profile, member), view=view)

# --- NOVO: COMANDO -roll ---
@bot.command(name="rollaaaa")
async def roll(ctx, dice: str = "1d20"):
    """
    Rola dados. Garante que cada rolagem nunca seja abaixo de 7 (ou seja, acima de 6).
    Uso:
      - -roll            -> rola 1d20 (mas mínimo 7)
      - -roll 2d6        -> rola 2 dados de 6 faces (cada um será no mínimo 7 por regra solicitada)
      - -roll 10         -> rola 1 dado de 10 faces (mínimo 7)
    Observação: a regra do usuário foi aplicada literalmente — cada valor menor ou igual a 6 é substituído por 7.
    """
    # Parsing simples: NdM ou número
    try:
        if 'd' in dice.lower():
            parts = dice.lower().split('d')
            n = int(parts[0]) if parts[0] else 1
            m = int(parts[1]) if parts[1] else 20
        else:
            n = 1
            m = int(dice)
    except Exception:
        n = 1
        m = 20

    # Limitar n para evitar abuso
    if n < 1:
        n = 1
    if n > 50:
        n = 50

    rolls = []
    for _ in range(n):
        r = random.randint(1, m if m > 1 else 20)
        # Garantir que nunca seja abaixo de 7
        if r <= 6:
            r = 7
        rolls.append(r)

    total = sum(rolls)
    if n == 1:
        await ctx.reply(f"{ctx.author.mention} rolou 🎲: **{rolls[0]}** (mínimo forçado 7)")
    else:
        await ctx.reply(f"{ctx.author.mention} rolou `{n}d{m}` → {rolls} = **{total}** (valores <=6 forçados para 7)")

@bot.command(name="ajuda")
async def ajuda(ctx):
    await ctx.send("Comandos: `-perfil`, `-editarperfil`, `-rolls`, `-roll`, `-ajuda`")

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if token:
        bot.run(token)
    else:
        print("Erro: DISCORD_TOKEN não encontrado.")