import io
import pydub
import discord
import asyncio
from discord import Option
from discord.ext.commands import Converter
from discord.ui import View, Button
from typing import Union, Dict, List


bot = discord.Bot(intents=discord.Intents.all())

class CustomBoolArgument(Converter):
	async def convert(cls, _, arg):
		return arg == cls.choices[0]
	
class UsersToRecordArg(CustomBoolArgument):
	choices = ('Record only me', 'Record all users in a channel')

voice_message_recorders: Dict[int, Union[None, bool]] = {}
max_voice_message_len_seconds = 120

@bot.slash_command(name='voice_message', description='Record a voice message')
async def __voice_message(
	ctx: discord.ApplicationContext, 
	users_to_record: Option(UsersToRecordArg, 'Users whose audio needs to be recorded', choices=UsersToRecordArg.choices, required=False, default=True),
	):
	voice = ctx.author.voice

	if not ctx.guild.voice_channels:
		return await ctx.respond(embed=discord.Embed(description=f'{ctx.author.mention}, a voice channel is required on the server to record a message', color=discord.Color.red()), ephemeral=True, delete_after=10)
	if not voice:
		connect_link = f'[connect]({(await ctx.guild.voice_channels[0].create_invite()).url})'
		return await ctx.respond(embed=discord.Embed(description=f'{ctx.author.mention}, **{connect_link}** to the voice channel to record a message', color=discord.Color.red()), ephemeral=True, delete_after=10)

	if ctx.author.id in voice_message_recorders.keys():
		return await ctx.respond(embed=discord.Embed(description=f'{ctx.author.mention}, finish recording the previous message first!', color=discord.Color.red()), ephemeral=True, delete_after=10)

	vc: discord.VoiceClient = await voice.channel.connect()
	voice_message_recorders[ctx.author.id] = None

	vc.start_recording(
		discord.sinks.MP3Sink(),
		send_voice_message,
		ctx.author,
		ctx.channel,
		users_to_record,
		sync_start=True
	)
	
	view = View(timeout=None)
	for emoji in ('✅', '🚫'):
		button = Button(
			custom_id=emoji,
			emoji=emoji,
			style=discord.ButtonStyle.blurple
		)
		button.callback = lambda i: stop_voice_message(ctx, vc, i)
		view.add_item(button)

	embed = discord.Embed(
		description=f'{ctx.author.mention}, recording has started. To complete or cancel your recording, click the button below.', 
		color=discord.Color.gold()
	)
	message = await (await ctx.respond(embed=embed, view=view)).original_response()

	timer = 0
	while (ctx.author.id in voice_message_recorders
			and voice_message_recorders[ctx.author.id] == None
			and timer < max_voice_message_len_seconds):
		await asyncio.sleep(1)
		timer += 1

		if timer > max_voice_message_len_seconds / 2 and timer % 5 == 0:
			embed.set_footer(text=f'There are approximately {max_voice_message_len_seconds - timer} seconds left before the recording automatically ends.')
			await message.edit(embed=embed)

	if ctx.author.id in voice_message_recorders and voice_message_recorders[ctx.author.id] == None:
		await message.edit(embed=discord.Embed(description=f'{ctx.author.mention}, recording is complete. To send or delete a post, click the button below.', color=discord.Color.green()), delete_after=60)
		vc.stop_recording()

async def stop_voice_message(ctx: discord.ApplicationContext, vc: discord.VoiceClient, interaction: discord.Interaction):
	if interaction.user != ctx.author:
		return
	
	await interaction.message.delete()
	voice_message_recorders[ctx.author.id] = interaction.custom_id == '✅'
	
	if vc.recording:
		vc.stop_recording()

async def wait_for_submit(user: discord.Member) -> None:
	iters = 0
	while voice_message_recorders[user.id] == None:
		await asyncio.sleep(0.5)
		iters += 1
		if iters == 120:
			voice_message_recorders[user.id] = False

async def send_voice_message(sink: discord.sinks.MP3Sink, author: discord.Member, channel: discord.TextChannel, record_only_author: bool):
	await sink.vc.disconnect()
	await wait_for_submit(author)

	recording_result = voice_message_recorders.pop(author.id)
	if not recording_result:
		return

	recorded_users = [user_id for user_id in sink.audio_data.keys()]

	if record_only_author and author.id in recorded_users:
		return await channel.send(
			f'Voice message from {author.mention}', 
			file=discord.File(sink.audio_data[author.id].file, f'{author.id}.{sink.encoding}')
		)

	mentions = [f'<@{user_id}>' for user_id in recorded_users]
	audio_segs: List[pydub.AudioSegment] = []
	longest = pydub.AudioSegment.empty()

	for audio in sink.audio_data.values():
		seg = pydub.AudioSegment.from_file(audio.file, format='mp3')
		if len(seg) > len(longest):
			audio_segs.append(longest)
			longest = seg
		else:
			audio_segs.append(seg)
		audio.file.seek(0)

	for seg in audio_segs:
		longest = longest.overlay(seg)

	with io.BytesIO() as f:
		longest.export(f, format="mp3")
		await channel.send(
			f'Voice message from {", ".join(mentions)}', 
			file=discord.File(f, filename=f'voice_message.mp3')
		)

bot.run('TOKEN')
