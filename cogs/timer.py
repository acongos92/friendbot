import discord
import pytz
import asyncio
import time
import requests
import re
import shlex
import decimal
import random
from math import ceil, floor
from itertools import product
from discord.utils import get        
from datetime import datetime, timezone,timedelta
from discord.ext import commands
from bfunc import numberEmojis, calculateTreasure, timeConversion, gameCategory, commandPrefix, roleArray, timezoneVar, currentTimers, db, callAPI, traceBack, settingsRecord, alphaEmojis, questBuffsDict, questBuffsArray, noodleRoleArray, checkForChar, tier_reward_dictionary, cp_bound_array, settingsRecord
from pymongo import UpdateOne
from cogs.logs import generateLog
from pymongo.errors import BulkWriteError


class Timer(commands.Cog):
    def __init__ (self, bot):
        self.bot = bot

    @commands.group(aliases=['t'], case_insensitive=True)
    async def timer(self, ctx):	
        pass

    @timer.command()
    async def help(self,ctx, page="1"):
        helpCommand = self.bot.get_command('help')
        if page == "2":
            await ctx.invoke(helpCommand, pageString='timer2')
        else:
            await ctx.invoke(helpCommand, pageString='timer')

    async def cog_command_error(self, ctx, error):
        msg = None
        if isinstance(error, commands.CommandOnCooldown):
            msg = f"A timer is already prepared in this channel. Please cancel the current timer and try again." 
        elif isinstance(error, commands.MissingAnyRole):
            msg = "You do not have the required permissions for this command."        
        elif isinstance(error, commands.UnexpectedQuoteError) or isinstance(error, commands.ExpectedClosingQuoteError) or isinstance(error, commands.InvalidEndOfQuotedStringError):
             msg = "Your \" placement seems to be messed up.\n"
        elif isinstance(error, commands.BadArgument):
            # convert string to int failed
            return
        else:
            if isinstance(error, commands.MissingRequiredArgument):
                print(error.param.name)
                if error.param.name == 'userList':
                    msg = "You can't prepare a timer without any players! \n"
                elif error.param.name == 'game':
                    msg = "You can't prepare a timer without a game name! \n"
                else:
                    msg = "Your command was missing an argument! "
            
            if msg:
                if ctx.command.name == "prep":
                    msg += f'Please follow this format:\n```yaml\n{commandPrefix}timer prep "@player1, @player2, @player3, [...]" quest name```'
                
                ctx.command.reset_cooldown(ctx)
                await ctx.channel.send(content=msg)
            else:
                ctx.command.reset_cooldown(ctx)
                await traceBack(ctx,error)


    
    """
    This is the command meant to setup a timer and allowing people to sign up. Only one of these can be active at a time in a single channel
    The command gets passed in a list of players as a single entry userList
    the last argument passed in will be treated as the quest name
    """
    @commands.cooldown(1, float('inf'), type=commands.BucketType.channel) 
    @commands.has_any_role('D&D Friend', 'Campaign Friend')
    @timer.command()
    async def prep(self, ctx, userList, *, game):
        #this checks that only the author's response with one of the Tier emojis allows Tier selection
        #the response is limited to only the embed message
        numberEmojisExtra = ['0️⃣','1️⃣','2️⃣','3️⃣','4️⃣','5️⃣','6️⃣','7️⃣','8️⃣','9️⃣']
        def startEmbedcheck(r, u):
            sameMessage = False
            if  prepEmbedMsg.id == r.message.id:
                sameMessage = True
            return (r.emoji in numberEmojisExtra[:6] or str(r.emoji) == '❌') and u == author and sameMessage
        #simplifying access to various variables
        channel = ctx.channel
        author = ctx.author
        #the name shown on the server
        user = author.display_name
        #the general discord name
        userName = author.name
        guild = ctx.guild
        #information on how to use the command, set up here for ease of reading and repeatability
        prepFormat =  f'Please follow this format:\n```yaml\n{commandPrefix}timer prep "@player1, @player2, @player3, [...]" "quest name"```'
        #check if the current channel is a campaign channel
        isCampaign = "campaign" in channel.category.name.lower()
        #prevent the command if not in a proper channel (game/campaign)
        if channel.category.id != settingsRecord[str(ctx.guild.id)]["Game Rooms"]:
            #exception to the check above in case it is a testing channel
            if str(channel.id) in settingsRecord['Test Channel IDs'] or channel.id in [728456736956088420, 757685149461774477, 757685177907413092]:
                pass
            else: 
                #inform the user of the correct location to use the command and how to use it
                await channel.send('Try this command in a game channel! ' + prepFormat)
                #permit the use of the command again
                self.timer.get_command('prep').reset_cooldown(ctx)
                return
        #check if the userList was given in the proper way or if the norewards option was taken, this avoids issues with the game name when multiple players sign up
        if '"' not in ctx.message.content:
            #this informs the user of the correct format
            await channel.send(f"Make sure you put quotes **`\"`** around your list of players and retry the command!\n\n{prepFormat}")
            #permit the use of the command again
            self.timer.get_command('prep').reset_cooldown(ctx)
            return
        #check if the prep command included any channels, the response assumes that this was as a result of trying to add a guild
        if ctx.message.channel_mentions != list():
            #inform the user on the proper way of adding guilds to the game
            await channel.send(f"It looks like you are trying to add a channel/guild to your timer.\nPlease do this during `***{commandPrefix}timer prep***` and not before.\n\n{prepFormat}")
            self.timer.get_command('prep').reset_cooldown(ctx)
            return
        #create an Embed object to use for user communication and information
        prepEmbed = discord.Embed()
        
        #check if the user mentioned themselves in the command, this is also meant to avoid having the user be listed twice in the roster below
        if author in ctx.message.mentions:
            #inform the user of the proper command syntax
            await channel.send(f"You cannot start a timer with yourself in the player list! {prepFormat}")
            self.timer.get_command('prep').reset_cooldown(ctx)
            return 

        # create a list of all expected players for the game so far, including the user who will always be the first 
        # element creating an invariant of the DM being the first element
        playerRoster = [author] + ctx.message.mentions

        # player limit + 1 (includes DM)
        playerLimit = 7 + 1 

        if len(playerRoster) > playerLimit:
            await channel.send(f'You cannot start a timer with more than {playerLimit - 1} players. Please try again.')
            self.timer.get_command('prep').reset_cooldown(ctx)
            return

        # set up the user communication for tier selection, this is done even if norewards is selected
        prepEmbed.add_field(name=f"React with [0-5] for the tier of your quest: **{game}**.\n", value=f"{numberEmojisExtra[0]} Tutorial One-shot (Level 1)\n {numberEmojisExtra[1]} Junior Friend (Level 1-4)\n{numberEmojisExtra[2]} Journeyfriend (Level 5-10)\n{numberEmojisExtra[3]} Elite Friend (Level 11-16)\n{numberEmojisExtra[4]} True Friend (Level 17-19)\n{numberEmojisExtra[5]} Ascended Friend (Level 17+)\n", inline=False)
        # the discord name is used for listing the owner of the timer
        prepEmbed.set_author(name=userName, icon_url=author.avatar_url)
        prepEmbed.set_footer(text= "React with ❌ to cancel.")
        # setup the variable to access the message for user communication
        prepEmbedMsg = None

        try:
            #if the channel is not a campaign channel we need the user to select a tier for the game
            if not isCampaign:
                #create the message to begin talking to the user
                prepEmbedMsg = await channel.send(embed=prepEmbed)
                # the emojis for the user to react with
                for num in range(0,6): await prepEmbedMsg.add_reaction(numberEmojisExtra[num])
                await prepEmbedMsg.add_reaction('❌')
                # get the user who reacted and what they reacted with, this has already been limited to the proper emoji's and proper user
                tReaction, tUser = await self.bot.wait_for("reaction_add", check=startEmbedcheck, timeout=60)
        except asyncio.TimeoutError:
            # the user does not respond within the time limit, then stop the command execution and inform the user
            await prepEmbedMsg.delete()
            await channel.send('Timer timed out! Try starting the timer again.')
            self.timer.get_command('prep').reset_cooldown(ctx)
            return

        else:
            #create the role variable for future use, default it to no role
            role = ""
            #continue our Tier check from above in case it is not a campaign
            if not isCampaign:
                await asyncio.sleep(1) 
                #clear reactions to make future communication easier
                await prepEmbedMsg.clear_reactions()
                #cancel the command based on user desire
                if tReaction.emoji == '❌':
                    await prepEmbedMsg.edit(embed=None, content=f"""Timer cancelled. Use the following command to prepare a timer:\n```yaml\n{commandPrefix}timer prep "@player1, @player2, @player3, [...]" quest name```""")
                    self.timer.get_command('prep').reset_cooldown(ctx)
                    return
                # otherwise take the role based on which emoji the user reacted with
                # the array is stored in bfunc and the options are 'New', 'Junior', 'Journey', 'Elite' and 'True' in this order
                role = roleArray[int(tReaction.emoji[0])]

            
        #clear the embed message
        prepEmbed.clear_fields()
        await prepEmbedMsg.clear_reactions()
        # if is not a campaign add the selected tier to the message title and inform the users about the possible commands (signup, add player, remove player, add guild)
        if not isCampaign:
            prepEmbed.title = f"{game} (Tier {roleArray.index(role)})"
            prepEmbed.description = f"**Signup**: {commandPrefix}timer signup \"character name\" \"consumable1, consumable2, [...]\"\n**Add to roster**: {commandPrefix}timer add @player\n**Remove from roster**: {commandPrefix}timer remove @player\n**Set guild**: {commandPrefix}timer guild #guild1, #guild2, #guild3"

        else:
            # otherwise give an appropriate title and inform about the limited commands list (signup, add player, remove player)
            prepEmbed.title = f"{game} (Campaign)"
            prepEmbed.description = f"**Signup**: {commandPrefix}timer signup\n**Add to roster**: {commandPrefix}timer add @player\n**Remove from roster**: {commandPrefix}timer remove @player"
        #setup a variable to store the string showing the current roster for the game
        rosterString = ""
        #now go through the list of the user/DM and the initially given player list and build a string
        for p in playerRoster:
            #since the author is always the first entry this if statement could be extracted, but the first element would have to be skipped
            #extracting could make the code marginally faster
            if p == author:
                #set up the special field for the DM character
                prepEmbed.add_field(name = f"{author.display_name} **(DM)**", value = "The DM has not signed up a character for DM rewards.")
            else:
                # create a field in embed for each player and their character, they could not have signed up so the text reflects that
                # the text differs only slightly if it is a campaign
                if not isCampaign:
                    prepEmbed.add_field(name=p.display_name, value='Has not yet signed up a character to play.', inline=False)
                else:
                    prepEmbed.add_field(name=p.display_name, value='Has not yet signed up for the campaign.', inline=False)
        #set up a field to inform the DM on how to start the timer or how to get help with it
        prepEmbed.set_footer(text= f"If enough players have signed up, use the following command to start the timer: {commandPrefix}timer start\nUse the following command to see a list of timer commands: {commandPrefix}timer help")

        # if it is a campaign or the previous message somehow failed then the prepEmbedMsg would not exist yet send we now send another message
        if not prepEmbedMsg:
            prepEmbedMsg = await channel.send(embed=prepEmbed)
        else:
            #otherwise we just edit the contents
            await prepEmbedMsg.edit(embed=prepEmbed)
        
        # set up all the guild related variables
        guildsList = []
        guildsCollection = db.guilds
        guildRecordsList = []
        guildBuffs = {}
        
        # create a list of all player and characters they have signed up with
        # this is a nested list where the contained entries are [member object, DB character entry, Consumable list for the game, character DB ID]
        # currently this starts with a dummy initial entry for the DM to enable later users of these entries in the code
        # this entry will be overwritten if the DM signs up with a game
        # the DM entry will always be the front entry, this property is maintained by the code
        signedPlayers = [[author,"No Rewards",['None'],"None", 
                            {"Consumables": {"Add": [], "Remove": []}, 
                             "Inventory": {"Add": [], "Remove": []},
                             "Magic Items": []}]]
        # signedPlayers +=[[self.bot.user,{"User ID": "203948352973438995", "Name": "MinVOrc 1", "Level": 19, "HP": 11, "Class": "Monk", " Background": "Waterdhavian Noble", "STR": 17, "DEX": 15, "CON": 16, "INT": 8, "WIS": 8, "CHA": 8, "CP": 0, "Current Item": "Dorfer Greataxe (3.0/6.0)", "GP": 0, "Magic Items": "None", "Consumables": "None", "Feats": "None", "Games":0, "Race": "Minotaur"},['None'],"5ecc5237f67beaca7943d350", {"Consumables": {"Add": [], "Remove": []},"Inventory": {"Add": [], "Remove": []},"Magic Items": []}], 
                            # [self.bot.user,{"User ID": "203948352973438995", "Name": "MinVOrc 2", "Level": 19, "HP": 11, "Class": "Monk", " Background": "Waterdhavian Noble", "STR": 17, "DEX": 15, "CON": 16, "INT": 8, "WIS": 8, "CHA": 8, "CP": 9, "Current Item": "Dorfer Greataxe (3.0/6.0)", "GP": 0, "Magic Items": "None", "Consumables": "None", "Feats": "None", "Games":0, "Race": "Minotaur"},['None'],"5ecc5237f67beaca7943d350",  {"Consumables": {"Add": [], "Remove": []},"Inventory": {"Add": [], "Remove": []},"Magic Items": []}], 
                            # [self.bot.user,{"User ID": "203948352973438995", "Name": "MinVOrc 3", "Level": 20, "HP": 11, "Class": "Monk", " Background": "Waterdhavian Noble", "STR": 17, "DEX": 15, "CON": 16, "INT": 8, "WIS": 8, "CHA": 8, "CP": 1, "Current Item": "Dorfer Greataxe (3.0/6.0)", "GP": 0, "Magic Items": "None", "Consumables": "None", "Feats": "None", "Games":0, "Race": "Minotaur"},['None'],"5ecc5237f67beaca7943d350",  {"Consumables": {"Add": [], "Remove": []},"Inventory": {"Add": [], "Remove": []},"Magic Items": []}]]

        #set up a variable for the current state of the timer
        timerStarted = False
        
        # create a list of all possible commands that could be used during the signup phase
        timerAlias = ["timer", "t"]
        timerCommands = ['signup', 'cancel', 'guild', 'start', 'add', 'remove']
      
        timerCombined = []
        # pair up each command group alias with a command and store it in the list
        for x in product(timerAlias,timerCommands):
            timerCombined.append(f"{commandPrefix}{x[0]} {x[1]}")
        
        """
        This is the heart of the command, this section runs continuously until the start command is used to change the looping variable
        during this process the bot will wait for any message that contains one of the commands listed in timerCombined above 
        and then invoke the appropriate method afterwards, the message check is also limited to only the channel signup was called in
        Relevant commands all have blocks to only run when called
        """
        while not timerStarted:
            # get any message that managed to satisfy the check described above, it has to be a command as a result
            msg = await self.bot.wait_for('message', check=lambda m: any(x in m.content for x in timerCombined) and m.channel == channel)
            """
            the following commands are all down to check which command it was
            the checks are all doubled up since the commands can start with $t and $timer
            the current issue is that it will respond to any message containing these strings, not just when they are at the start
            """
            
            """
            The signup command has different behaviors if the signup is from the DM, a player or campaign player
            
            """
            if msg.content.startswith(f"{commandPrefix}timer signup") or msg.content.startswith(f"{commandPrefix}t signup"):
                # if the message author is the one who started the timer, call signup with the special DM moniker
                # the character is extracted from the message in the signup command 
                # special behavior:
                playerChar = None
                if msg.author in playerRoster and msg.author == author:
                    playerChar = await ctx.invoke(self.timer.get_command('signup'), char=msg, author=msg.author, role='DM') 
                # allow for people in the roster to sign up with their characters
                # if it is a campaign then no character is needed, thus the message with the character is not passed through
                elif msg.author in playerRoster:
                    if not isCampaign:
                        playerChar = await ctx.invoke(self.timer.get_command('signup'), char=msg, author=msg.author, role=role) 
                    else:
                        # if this is for a campaign we set char to a special value that signals signup that this is for a campaign
                        playerChar = await ctx.invoke(self.timer.get_command('signup'), char=None, author=msg.author, role=role) 
                # if the message author has not been permitted to the game yet, inform them of such
                # a continue statement could be used to skip the following if statement
                else:
                    await channel.send(f"***{msg.author.display_name}***, you must be on the roster in order to participate in this quest.")
                
                """
                if the signup command successfuly returned a player record ([author, char, consumables, char id])
                we then can process these and add the signup to the roster
                """
                if playerChar:
                    # this check is meant to see if the player who is signing up is the DM
                    # Since the DM is always the front element this check will always work and 
                    if playerRoster.index(playerChar[0]) == 0:
                        #update the the specific info about the DM sign up
                        prepEmbed.set_field_at(0, name=f"{author.display_name} **(DM)**", value= f"***{playerChar[1]['Name']}*** will receive DM rewards.", inline=False)
                        # with the dummy element can now be replaced with a more straight forward check
                        if playerChar[0] in [s[0] for s in signedPlayers]:
                            signedPlayers[0] = playerChar
                        else:
                            signedPlayers.insert(0,playerChar)
                    else:
                        # for campaigns only the name of the player is important, but for one shats the Name field wield be extracted from the Character entry, various important information is also added and the consumable list is connected
                        if not isCampaign:
                            prepEmbed.set_field_at(playerRoster.index(playerChar[0]), name=f"{playerChar[1]['Name']}", value= f"{playerChar[0].mention}\nLevel {playerChar[1]['Level']}: {playerChar[1]['Race']} {playerChar[1]['Class']}\nConsumables: {', '.join(playerChar[2]).strip()}\n", inline=False)
                        else:
                            prepEmbed.set_field_at(playerRoster.index(playerChar[0]), name=playerChar[0].name, value= f"{playerChar[0].mention}", inline=False)
                        
                        # this sections checks if the player had signed up before and updates their character entry
                        # otherwise they get added to the bottom
                        foundSignedPlayer = False
                        for s in range(len(signedPlayers)):
                            # s here is the index of a signedPlayers entry
                            # this checks looks for equivalent Member objects
                            # signedPlayers is a list of arrays like playerChar
                            if playerChar[0] == signedPlayers[s][0]:
                                signedPlayers[s] = playerChar
                                foundSignedPlayer = True
                                break
                        if not foundSignedPlayer:
                            signedPlayers.append(playerChar)
                        

            # similar issues arise as mentioned above about wrongful calls
            elif (msg.content.startswith(f"{commandPrefix}timer add ") or msg.content.startswith(f"{commandPrefix}t add ")):
                if await self.permissionCheck(msg, author):
                    if len(playerRoster) + 1 > playerLimit:
                        await channel.send(f'You cannot add more than {playerLimit - 1} players to the timer.')
                    else:
                        # this simply checks the message for the user that is being added, the Member object is returned
                        addUser = await ctx.invoke(self.timer.get_command('add'), msg=msg, prep=True)
                        #failure to add a user does not have an error message if no user is being added
                        if addUser is None:
                            pass
                        elif addUser not in playerRoster:
                            # set up the embed fields for the new user if they arent in the roster yet
                            if not isCampaign:
                                prepEmbed.add_field(name=addUser.display_name, value='Has not yet signed up a character to play.', inline=False)
                            else:
                                prepEmbed.add_field(name=addUser.display_name, value='Has not yet signed up for the campaign.', inline=False)
                            # add them to the roster
                            playerRoster.append(addUser)
                        else:
                            #otherwise inform the user of the failed add
                            await channel.send(f'***{addUser.display_name}*** is already on the timer.')

            # same issues arise again
            
            elif (msg.content.startswith(f"{commandPrefix}timer remove ") or msg.content.startswith(f"{commandPrefix}t remove ")) :
                if await self.permissionCheck(msg, author):
                    # this simply checks the message for the user that is being added, the Member object is returned
                    removeUser = await ctx.invoke(self.timer.get_command('remove'), msg=msg, start=playerRoster, prep=True)
                    print (removeUser)
                    if removeUser is None:
                        pass
                    #check if the user is not the DM
                    elif playerRoster.index(removeUser) != 0:
                        # remove the embed field of the player
                        prepEmbed.remove_field(playerRoster.index(removeUser))
                        # remove the player from the roster
                        playerRoster.remove(removeUser)
                        # remove the player from the signed up players
                        for s in signedPlayers:
                            if removeUser in s:
                                signedPlayers.remove(s)
                    else:
                        await channel.send('You cannot remove yourself from the timer.')

            #the command that starts the timer, it does so by allowing the code to move past the loop
            elif (msg.content == f"{commandPrefix}timer start" or msg.content == f"{commandPrefix}t start"):
                if await self.permissionCheck(msg, author):
                    if len(signedPlayers) == 1:
                        await channel.send(f'There are no players signed up! Players, use the following command to sign up to the quest with your character before the DM starts the timer:\n```yaml\n{commandPrefix}timer signup```') 
                    else:
                        timerStarted = True
            #the command that cancels the timer, it does so by ending the command all together                              
            elif (msg.content == f"{commandPrefix}timer cancel" or msg.content == f"{commandPrefix}t cancel"):
                if await self.permissionCheck(msg, author):
                    await channel.send(f'Timer cancelled! If you would like to prep a new quest, use the following command:\n```yaml\n{commandPrefix}timer prep "@player1, @player2, @player3, [...]" quest name```') 
                    # allow the call of this command again
                    self.timer.get_command('prep').reset_cooldown(ctx)
                    return

            elif (msg.content.startswith(f'{commandPrefix}timer guild') or msg.content.startswith(f'{commandPrefix}t guild')):
                if await self.permissionCheck(msg, author):
                    guildsList = []
                    guildsListStr = ""
                    guildCategoryID = settingsRecord[str(ctx.guild.id)]["Guild Rooms"]

                    if (len(msg.channel_mentions) > 2):
                        await channel.send(f"The number of guilds exceeds two. Please follow this format and try again:\n```yaml\n{commandPrefix}timer guild #guild1 #guild2```") 
                    elif msg.channel_mentions != list():
                        guildsList = msg.channel_mentions
                        invalidChannel = False
                        guildRecordsList = []
                        guildsListStr = "Guilds: " 
                        # TODO: Guilds on DM
                        for g in guildsList:
                            if g.category_id != guildCategoryID:
                                invalidChannel = True
                                await channel.send(f"***{g}*** is not a guild channel. Please follow this format and try again:\n```yaml\n{commandPrefix}timer guild #guild1, #guild2```") 
                                guildsList = []
                                break
                                
                        if not invalidChannel:
                            prepEmbed.description = f"Guilds: {', '.join([g.mention for g in guildsList])}\n**Signup**: {commandPrefix}timer signup \"character name\" \"consumable1, consumable2, [...]\"\n**Add to roster**: {commandPrefix}timer add @player\n**Remove from roster**: {commandPrefix}timer remove @player\n**Set guild**: {commandPrefix}timer guild #guild1, #guild2"
                    else:
                        await channel.send(f"I couldn't find any mention of a guild. Please follow this format and try again:\n```yaml\n{commandPrefix}timer guild #guild1, #guild2```") 

            await prepEmbedMsg.delete()
            prepEmbedMsg = await channel.send(embed=prepEmbed)
        await ctx.invoke(self.timer.get_command('start'), userList = signedPlayers, game=game, role=role, guildsList = guildsList)


    """
    This is the command used to allow people to enter their characters into a game before the timer starts
    char is a message object which makes the default value of "" confusing as a mislabel of the object
    role is a string indicating which tier the game is for or if the player signing up is the DM
    resume is boolean quick check to see if the command was invoked by the resume command   
        this property is technically not needed since it could quickly be checked, 
        but it does open the door to creating certain behaviors even if not commaning from $resume
        the current state would only allow this from prep though, which never sets this property
        The other way around does not work, however since checking for it being true instead of checking for
        the invoke source (ctx.invoked_with == "resume") would allow manual calls to this command
    """
    @timer.command()
    async def signup(self,ctx, char="", author="", role="", resume=False):
        #check if the command was called using one of the permitted other commands
        if ctx.invoked_with == 'prep' or ctx.invoked_with == "resume":
            # set up a informative error message for the user
            signupFormat = f'Please follow this format:\n```yaml\n{commandPrefix}timer signup "character name" "consumable1, consumable2, [...]"```'
            # create an embed object
            charEmbed = discord.Embed()
            # set up the variable for the message for charEmbed
            charEmbedmsg = None
            #get quicker access to some variables from the context
            channel = ctx.channel
            guild = ctx.guild
            # set up the string for the consumables list
            consumablesList = ""
            # This is only true if this is during a campaign, in that case there are no characters or consumables
            if char is None: 
                usersCollection = db.users
                # grab the DB records of the first user with the ID of the author
                userRecord = list(usersCollection.find({"User ID": str(author.id)}))[0]
                # this indicates a selection of user info that seems to never be used
                return [author, userRecord]
            # check if the entire message was just one of the triggering commands which indicates a lack of character
            if f'{commandPrefix}timer signup' == char.content.strip() or f'{commandPrefix}t signup' == char.content.strip():
                # According to Xyff this blocks the repeating of error messages when resume goes through all messages
                if ctx.invoked_with != "resume":
                    await channel.send(content=f'You did not input a character, please try again.\n\n{signupFormat}')
                    # this is a valid return, since the resume and sign up code will check for this before executing further
                return False
            #check which message caused the invocation to create different behaviors
            try:
                if 'timer signup ' in char.content or 't signup ' in char.content:
                    #shlex allows the splitting in a way that respects the '"' in the string and splits according to white space
                    #this retrieves the character + consumable list from the command 
                    # first the command part gets removed with the first split and then the remainder gets split like arguments for the command line
                    if f'{commandPrefix}timer signup ' in char.content:
                        charList = shlex.split(char.content.split(f'{commandPrefix}timer signup ')[1].strip())
                    elif f'{commandPrefix}t signup ' in char.content:
                        charList = shlex.split(char.content.split(f'{commandPrefix}t signup ')[1].strip())
                    # since the character is the first parameter after the command name this will get the char name
                    charName = charList[0]

                else:
                # this is a similar process to above but with the added adjustment that a player name is also included
                
                    if 'timer add ' in char.content or 't add ' in char.content:
                        if 'timer add ' in char.content:
                            charList = shlex.split(char.content.split(f'{commandPrefix}timer add ')[1].strip())
                        elif 't add' in char.content:
                            charList = shlex.split(char.content.split(f'{commandPrefix}t add ')[1].strip())
                        # since two parameters are needed for 'add' we need to inform the user
                        if len(charList) == 1:
                            # again block repeat messages in case of a resume command, the check is different for some reason
                            if not resume:
                                await ctx.channel.send("You're missing a character name for the player you're trying to add. Please try again.")
                            return
                        # in this case the character name is the second parameter
                        charName = charList[1]
                    # this is the exact same set up as for signup, since a person is adding themselves only one parameter is expected
                    elif ('timer addme ' in char.content or 't addme ' in char.content) and (char.content != f'{commandPrefix}timer addme ' or char.content != f'{commandPrefix}t addme '):
                        if 'timer addme ' in char.content:
                            charList = shlex.split(char.content.split(f'{commandPrefix}timer addme ')[1].strip())
                        elif 't addme ' in char.content:
                            charList = shlex.split(char.content.split(f'{commandPrefix}t addme ')[1].strip())
                        charName = charList[0]
                    else:
                        if not resume:
                            await ctx.channel.send("I wasn't able to add this character. Please check your format.")
                        return
            except ValueError as e:
                await ctx.channel.send("Something was off with your character name. Did you miss a quotation mark?")
                return
            # if the last parameter is not the character name then we know that the player registered consumables
            if charList[len(charList) - 1] != charName:
                # consumables are separated by ','
                consumablesList = list(map(lambda x: x.strip(), charList[len(charList) - 1].split(',')))


            # use the bfunc function checkForChar to handle character selection, gives us the DB entry of the character
            cRecord, charEmbedmsg = await checkForChar(ctx, charName, charEmbed, author, customError=True)
            
            if not cRecord:
                if not resume:
                    await channel.send(content=f'I was not able to find the character "***{charName}***"!\n\n{signupFormat}')
                return False

            if charEmbedmsg:
                await charEmbedmsg.delete()
            # this code should never execute since charName is either assigned a value or the code will already cancel the command
            # unless there is a way to call this command without using signup or add
            if charName == "" or charName is None:
                # block errors on resume
                if not resume:
                    await channel.send(content=f'You did not input a character!\n\n{signupFormat}')
                return False

            if 'Death' in cRecord:
                # block errors on resume
                if not resume:
                    await channel.send(content=f'You cannot sign up with ***{cRecord["Name"]}*** because they are dead. Please use the following command to resolve their death:\n```yaml\n{commandPrefix}death {cRecord["Name"]}```')
                return False 

            elif 'Respecc' in cRecord:
                # block errors on resume
                if not resume:
                    await channel.send(content=f'You cannot sign up with ***{cRecord["Name"]}*** because they need to respec. Please use the following command to resolve their death:\n```yaml\n{commandPrefix}respec {cRecord["Name"]} "new character name" "race" "class1 level / class2 level / class3 level / class4 level" "background" STR DEX CON INT WIS CHA```')
                return False 
            # check if there is any record of a game in charRecords
            elif next((s for s in cRecord.keys() if 'GID' in s), None):
                if not resume:
                    await channel.send(content=f'You cannot sign up with ***{cRecord["Name"]}*** because they have not received their rewards from their last quest. Please wait until the session log has been approved.')
                return False    
            # get how much CP the character has and how much they need
            cpSplit = cRecord['CP']
            validLevelStart = 1
            validLevelEnd = 1
            charLevel = cRecord['Level']
            
            # set up the bounds of which level the character is allowed to be
            if role == "Ascended":
                validLevelStart = 17
                validLevelEnd = 20
            elif role == "True":
                validLevelStart = 17
                validLevelEnd = 19
            elif role == "Elite":
                validLevelStart = 11
                validLevelEnd = 16
            elif role == "Journey":
                validLevelStart = 5
                validLevelEnd = 10
            elif role == "Junior":
                validLevelEnd = 4
            elif role == "New":
                validLevelEnd = 4
            elif role == "DM":
                validLevelEnd = 20
            
            tierNum=5
            # calculate the tier of the rewards
            if charLevel < 5:
                tierNum = 1
            elif charLevel < 11:
                tierNum = 2
            elif charLevel < 17:
                tierNum = 3
            elif charLevel < 20:
                tierNum = 4
            
            # block a character with an invalid level for the tier and inform the user
            if charLevel < validLevelStart or charLevel > validLevelEnd:
                if not resume:
                    await channel.send(f"***{cRecord['Name']}*** is not between levels {validLevelStart} - {validLevelEnd} to play in this quest. Please choose a different character.")
                return False 

            # if the character has more cp than needed for a level up, they need to perform that level up first so we block the command
            if charLevel <20 and cpSplit >= cp_bound_array[tierNum-1][0]:
                if not resume:
                    await channel.send(content=f'You need to level up ***{cRecord["Name"]}*** before they can join the quest! Use the following command to level up:\n```yaml\n{commandPrefix}levelup "character name"```')
                return False 

            # handle the list of consumables only if it is not empty
            # there is also a special block for DMs since they can't use consumables
            if consumablesList and role != "DM":
                #get all consumables the character has
                charConsumables = {}
                for c in cRecord['Consumables'].split(', '):
                    if c not in charConsumables:
                        charConsumables[c] = 1
                    else:
                        charConsumables[c] += 1

                
                gameConsumables = []
                checkedIndices = []
                notValidConsumables = ""
                # This sets up how many consumables are permitted based on the character level
                consumableLength = 2 + (charLevel-1)//4
                if("Ioun Stone (Mastery)" in cRecord['Magic Items']):
                    consumableLength += 1
                # block the command if more consumables than allowed (limit or available) are being registed
                if len(consumablesList) > consumableLength:
                    if not resume:
                        await channel.send(content=f'You are trying to bring in too many consumables (**{len(consumablesList)}/{consumableLength}**)! The limit for your character is **{consumableLength}**.')
                    return False
                
                #loop over all consumable pairs and check if the listed consumables are in the inventory

                #this code is completely non-functional
                # the else will execute if the first element of charConsumables is not the listed item
                # this means that only that first entry can be brought as it never get to check past that
                # this can be fixed by doing using a variable that checks if has been found and maintaining it and then doing a check after the inner loop finishes

                # consumablesList is the consumable list the player intends to bring
                # charConsumables are the consumables that the character has available.
                # gameConsumables are the final list of consumables characters are bringing
                for i in consumablesList:
                    itemFound = False
                    for jk, jv in charConsumables.items():
                        if i.strip() != "" and i.lower().replace(" ", "").strip() in jk.lower().replace(" ", ""):
                            if jv > 0 :
                                gameConsumables.append(jk.strip())
                                charConsumables[jk] -= 1
                                itemFound = True
                                break

                    if not itemFound:
                        notValidConsumables += f"`• {i.strip()}`\n"
                        

                # if there were any invalid consumables, inform the user on which ones cause the issue
                if notValidConsumables:
                    if not resume:
                        await channel.send(f"These items were not found in your character's inventory:\n{notValidConsumables}")
                    return False
                # If no consumables were listed, create a special entry
                if not gameConsumables:
                    gameConsumables = ['None']
                # this sets up the player list of the game, it stores who it is, all the consumables and which character they are using and their stuff
                return [author,cRecord,gameConsumables, cRecord['_id'],
                            {"Consumables": {"Add": [], "Remove": []}, 
                             "Inventory": {"Add": [], "Remove": []},
                             "Magic Items": []}]

            # since no consumables were listed we can default to the special None option
            return [author,cRecord,['None'],cRecord['_id'], 
                            {"Consumables": {"Add": [], "Remove": []}, 
                             "Inventory": {"Add": [], "Remove": []},
                             "Magic Items": []}]



    """
    This command is used to remove consumables during play time
    msg -> the msg that caused the invocation
    start -> a dictionary of strings and player list pairs, the strings are made out of the kind of reward and the duration and the value is a list of players entries (format can be found as the return value in signup)
    resume -> if this command has been called during the resume phase
    """
    @timer.command()
    async def deductConsumables(self, ctx, msg,start, resume=False): 
        if ctx.invoked_with == 'prep' or ctx.invoked_with == "resume":
            channel = ctx.channel
            # extract the name of the consumable and transform it into a standardized format
            searchQuery =  msg.content.split('-')[1].strip()
            searchItem = searchQuery.lower().replace(' ', '')
            timeKey = ""
            removedItem = ""
            if searchItem.startswith("+") and not searchItem[1].isnumeric() and not resume:
                await channel.send(f"You cannot remove reward items.")
                return start         
            # search through all entries for the player entry of the player
            for u, v in start.items():
                for item in v:
                    # if the entry is the one of the invoking user
                    if item[0] == msg.author:
                        # establish that we found the user
                        timeKey = u
                        currentItem = item
                        foundItem = None
                        # search through the users list of brough consumables 
                        # could have used normal for loop, we do not use the index
                        item_type = None
                        for j in currentItem[2]:
                            # if found than we can mark it as such
                            if searchItem == j.lower().replace(" ", ""):
                                foundItem = j
                                item_type = "Consumables"
                                break
                         
                        # inform the user if we couldnt find the item
                        if not foundItem:
                            for key, inv in currentItem[1]["Inventory"].items():
                                # if found than we can mark it as such
                                if searchItem == key.lower().replace(' ', '') and inv > 0:
                                    foundItem = key
                                    item_type = "Inventory"
                                    break  
                                    
                        if not foundItem:
                            if not resume:
                                await channel.send(f"I could not find the item **{searchQuery}** in your inventory in order to remove it.")
                                return start                      
                        else:
                            if item_type == "Consumables":
                                # remove the entry from the list of consumables of the character
                                charConsumableList = currentItem[1]['Consumables'].split(', ')
                                charConsumableList.remove(foundItem)
                                # remove the item from the brought consumables
                                currentItem[2].remove(foundItem) 
                                # update the characters consumables to reflect the item removal
                                currentItem[1]['Consumables'] = ', '.join(charConsumableList).strip()
                            elif item_type == "Inventory":
                                currentItem[1][item_type][foundItem] -= 1
                            currentItem[4][item_type]["Remove"].append(foundItem)
                            if not resume:
                                await channel.send(f"The item **{foundItem}** has been removed from your inventory.")

            # this variable is set when the user is found, thus this shows that the player was not on the timer
            if timeKey == "":
                if not resume:
                    await channel.send(f"Looks like you were trying to remove **{searchItem}** from your inventory. I could not find you on the timer to do that.")
            return start
    
    """
    This command is used to remove rewarded consumables during play time
    msg -> the msg that caused the invocation
    start -> a dictionary of strings and player list pairs, the strings are made out of the kind of reward and the duration and the value is a list of players entries (format can be found as the return value in signup)
    resume -> if this command has been called during the resume phase
    """
    async def undoConsumables(self, ctx, msg,start, dmChar, resume=False): 
        if ctx.invoked_with == 'prep' or ctx.invoked_with == "resume":
            channel = ctx.channel
            # search through all entries for the player entry of the player
            for u, v in start.items():
                for item in v: 
                    cList = []
                    for i in item[2]:
                        if i.startswith('+') and not i[1].isnumeric():
                            pass
                        else:
                            cList.append(i)
                    item[2] = cList
                    item[4]["Magic Items"]= []
                    item[4]["Consumables"]["Add"] = []
                    item[4]["Inventory"]["Add"] = []
            
            dmChar[4]["Magic Items"]= []
            dmChar[4]["Consumables"]["Add"] = []
            dmChar[4]["Inventory"]["Add"] = []
            dmChar[5][1] = {"Players" : {"Major":[], "Minor": []}, 
                                    "DM" : {"Major":[], "Minor": []}}
                    
            if not resume:
                await channel.send(f"All reward items have been removed.")

            return start
    
    
    """
    This command handles all the intial setup for a running timer
    this includes setting up the tracking variables of user playing times,
    """
    @timer.command()
    async def start(self, ctx, userList="", game="", role="", guildsList = ""):
        # access the list of all current timers, this list is reset on reloads and resets
        # this is used to enable the list command and as a management tool for seeing if the timers are working
        global currentTimers
        timerCog = self.bot.get_cog('Timer')
        # start cannot be invoked by resume since it has its own structure
        if ctx.invoked_with == 'prep': 
            # make some common variables more accessible
            channel = ctx.channel
            author = ctx.author
            user = author.display_name
            userName = author.name
            guild = ctx.guild
            # this uses the invariant that the DM is always the first signed up
            dmChar = userList.pop(0)
            # create an entry in the DM player entry that keeps track of rewards in the future
            dmChar.append(['Junior Noodle',{"Players" : {"Major":[], "Minor": []}, 
                                            "DM" : {"Major":[], "Minor": []}}])

            # find the name of which noodle role the DM has
            for r in dmChar[0].roles:
                if 'Noodle' in r.name:
                    dmChar[5][0] = r.name
                    break
            
            # get the current time for tracking the duration
            startTime = time.time()
            # format the time for a localized version defined in bfunc
            datestart = datetime.now(pytz.timezone(timezoneVar)).strftime("%b-%d-%y %I:%M %p")
            # create a list of entries to track players with
            start = []
            if role != "":
                # this step could be skipped by setting start = userList.copy
                # add all signed up players to the timer
                for u in userList:
                    start.append(u)
                # set up a dictionary for tracking timer rewards paired starting times
                startTimes = {f"{role} Friend Full Rewards:{startTime}":start} 
                
                roleString = ""
                roleString = f"({role})"
            else:
                # add all signed up players to the timer
                for u in userList:
                    start.append(u)
                # set up a dictionary to track player times
                startTimes = {f"No Rewards:{startTime}":start}
                roleString = "(Campaign)"  
            # Inform the user of the started timer
            await channel.send(content=f"Starting the timer for **{game}** {roleString}.\n" )
            # add the timer to the list of runnign timers
            currentTimers.append('#'+channel.name)
            
            # set up an embed object for displaying the current duration, help info and DM data
            stampEmbed = discord.Embed()
            stampEmbed.title = f'**{game}**: 0 Hours 0 Minutes\n'
            stampEmbed.set_footer(text=f'#{ctx.channel}\nType `{commandPrefix}help timer2` for help with a running timer.')
            stampEmbed.set_author(name=f'DM: {userName}', icon_url=author.avatar_url)

            
            # playerList is never used
            playerList = []
            if role != "":
                # for every player check their consumables and create a field in the embed to display them
                # this field also show the charater name
                for u in userList:
                    consumablesString = ""
                    if u[2] != ['None']:
                        consumablesString = "\nConsumables: " + ', '.join(u[2])
                    stampEmbed.add_field(name=f"**{u[0].display_name}**", value=f"**{u[1]['Name']}**{consumablesString}\n", inline=False)
            else:
                # if there are no rewards then consumables will always be None allowing us to shortcut the check
                for u in userList:
                    stampEmbed.add_field(name=f"**{u[0].display_name}**", value=u[0].mention, inline=False)
            

            stampEmbedmsg = await channel.send(embed=stampEmbed)

            ddmrw = settingsRecord["ddmrw"]
            # During Timer
            await timerCog.duringTimer(ctx, datestart, startTime, startTimes, role, game, author, stampEmbed, stampEmbedmsg,dmChar,guildsList, ddmrw = ddmrw)
            
            # allow the creation of a new timer
            self.timer.get_command('prep').reset_cooldown(ctx)
            # when the game concludes, remove the timer from the global tracker
            currentTimers.remove('#'+channel.name)
            return

    @timer.command()
    async def transfer(self,ctx,user=""):
        if ctx.invoked_with == 'start' or ctx.invoked_with == 'resume':
            guild = ctx.guild
            newUser = guild.get_member_named(user.split('#')[0])
            return newUser 

    """
    start -> a dictionary of strings and player list pairs, the strings are made out of the kind of reward and the duration and the value is a list of players entries (format can be found as the return value in signup)
    resume -> if this is during the resume process
    dmChar -> the player entry (format [member object, char DB entry, brought consumables, char id, item changes]) of the DM with an added entry [5] as [Noodle Role Name, majors  = 0, minors = 0, dmMajors = 0,dmMinors = 0]
    """    

    async def reward(self,ctx,msg, start="",resume=False, dmChar="", ):

        if ctx.invoked_with == 'prep' or ctx.invoked_with == 'resume':
            guild = ctx.guild
            # get the list of people receiving rewards
            rewardList = msg.raw_mentions
            rewardUser = ""
            # create an embed text object
            charEmbed = discord.Embed()
            charEmbedmsg = None
            
            # if nobody was listed, inform the user
            if rewardList == list():
                if not resume:
                    await ctx.channel.send(content=f"I could not find any mention of a user to hand out a reward item.") 
                #return the unchanged parameters
                return start,dmChar
            else:
                # get the first user mentioned
                rewardUser = guild.get_member(rewardList[0])
                startcopy = start.copy()
                userFound = False
                
                # if the user getting rewards is the DM we can save time by not going through the loop
                if rewardUser == dmChar[0] and dmChar[1]=="No Rewards":
                    if not resume:
                        await ctx.channel.send(content=f"You did not sign up with a character to reward items to.") 
                    #return the unchanged parameters
                    return start,dmChar
                elif rewardUser == dmChar[0]: 
                    userFound = True
                    # the player entry of the player getting the item
                    currentItem = dmChar
                    # list of current consumables on the character
                    # [1] in a player entry is the DB entry of the character
                    charConsumableList = currentItem[1]['Consumables'].split(', ')
                    # list of current magical items
                    charMagicList = currentItem[1]['Magic Items'].split(', ')
                    # character level
                    charLevel = int(currentItem[1]['Level'])
                # since this checks for multiple things, this cannot be avoided
                for u, v in startcopy.items():
                    if 'Full Rewards' in u:
                        totalDurationTime = (time.time() - float(u.split(':')[1]) + 3600 * 0) // 60 #Set multiplier to wanted hour shift 
                        if totalDurationTime < 180:
                            if not resume:
                              await ctx.channel.send(content=f"You cannot award any reward items if the quest is under three hours.") 
                            return start, dmChar

                    for item in v:
                        if dmChar[0] == rewardUser:
                            break
                        if item[0] == rewardUser:
                            userFound = True
                            # the player entry of the player getting the item
                            currentItem = item
                            # list of current consumables on the character
                            # [1] in a player entry is the DB entry of the character
                            charConsumableList = currentItem[1]['Consumables'].split(', ')
                            # list of current magical items
                            charMagicList = currentItem[1]['Magic Items'].split(', ')
                            # character level
                            charLevel = int(currentItem[1]['Level'])
                            
                if userFound:
                    if '"' in msg.content:
                        consumablesList = msg.content.split('"')[1::2][0].split(', ')

                    else:
                        if not resume:
                            await ctx.channel.send(content=f'You need to include quotes around the reward item in your command. Please follow this format and try again:\n```yaml\n{commandPrefix}timer reward @player "reward item1, reward item2, [...]"```')
                        return start, dmChar
                        
                    # the current counts of items rewarded
                    major = len(dmChar[5][1]["Players"]["Major"])
                    minor = len(dmChar[5][1]["Players"]["Minor"])
                    dmMajor = len(dmChar[5][1]["DM"]["Major"])
                    dmMinor = len(dmChar[5][1]["DM"]["Minor"])
                    
                    # if the DM has to pick a non-consumable
                    dmMnc = False
                    # if the DM has to pick a reward of a lower tier
                    lowerTier = False
                    # if the DM has to choose between major and minor
                    chooseOr = False

                    totalDurationTimeMultiplier = int(totalDurationTime // 180)
                    # set up the total reward item limits based on noodle roles
                    # check out hosting-a-one-shot for details
                    # Minor limit is the total sum of rewards allowed
                    
                    rewardMajorLimit = 1
                    rewardMinorLimit = 2
                    dmMajorLimit = 0
                    dmMinorLimit = 1
                    
                    if dmChar[5][0] == 'Eternal Noodle':
                        rewardMajorLimit = 4
                        rewardMinorLimit = 8
                        dmMajorLimit = 2
                        dmMinorLimit = 4
                    elif dmChar[5][0] == 'Immortal Noodle':
                        rewardMajorLimit = 3
                        rewardMinorLimit = 7
                        dmMajorLimit = 1
                        dmMinorLimit = 3
                    elif dmChar[5][0] == 'Ascended Noodle':
                        rewardMajorLimit = 3
                        rewardMinorLimit =  6
                        dmMajorLimit = 1
                        dmMinorLimit = 2
                    elif dmChar[5][0] == 'True Noodle':
                        rewardMajorLimit = 2
                        rewardMinorLimit = 5
                        dmMajorLimit = 1
                        dmMinorLimit = 1
                    elif dmChar[5][0] == 'Elite Noodle':
                        rewardMajorLimit = 2
                        rewardMinorLimit = 4
                        dmMajorLimit = 1
                        dmMinorLimit = 1
                        lowerTier = True
                        chooseOr = True
                    elif dmChar[5][0] == 'Good Noodle':
                        rewardMajorLimit = 1
                        rewardMinorLimit = 3
                        dmMajorLimit = 0
                        dmMinorLimit = 1
                        lowerTier = True
                    else:
                        dmMnc = True
                    tierNum=5
                    # calculate the tier of the rewards
                    if charLevel < 5:
                        tierNum = 1
                    elif charLevel < 11:
                        tierNum = 2
                    elif charLevel < 17:
                        tierNum = 3
                    elif charLevel < 20:
                        tierNum = 4
                        
                    # make adjustments to the tier number if it is the DM character and the role needs tier lowering
                    if lowerTier and rewardUser == dmChar[0]:
                        # set the minimum to 1
                        if tierNum < 2:
                            tierNum = 1
                        else:
                            tierNum -= 1

                    
                    dmMajorLimit += floor((totalDurationTimeMultiplier -1) / 2)
                    dmMinorLimit += (totalDurationTimeMultiplier -1)
                    
                    rewardMajorLimit += floor((totalDurationTimeMultiplier -1) / 2)
                    rewardMinorLimit += (totalDurationTimeMultiplier -1)
                    if dmMnc:
                        dmMinorLimit += dmMajorLimit
                        dmMajorLimit = 0
                    
                    player_type = "Players"
                    if rewardUser == dmChar[0]:
                        player_type = "DM"
                    
                    awarded_majors = []
                    awarded_minors = []
                    
                    character_add = {"Inventory": [], "Consumables": [], "Magic Items": []}
                    
                    blocking_list_additions = {"Major": [], "Minor" : []}
                    for query in consumablesList:
                        # TODO: Deal with this in resume, should not show embed
                        # if the player is getting a spell scoll then we need to determine which spell they are going for
                        # we do this by searching in the spell table instead
                        if 'spell scroll' in query.lower():
                            # extract the spell
                            spellItem = query.lower().replace("spell scroll", "").replace('(', '').replace(')', '')
                            # use the callAPI function from bfunc to search the spells table in the DB for the spell being rewarded
                            sRecord, charEmbed, charEmbedmsg = await callAPI(ctx, charEmbed, charEmbedmsg, 'spells', spellItem)
                            
                            # if no spell was found then we inform the user of the failure and stop the command
                            if not sRecord and not resume:
                                await ctx.channel.send(f'''**{query}** belongs to a tier which you do not have access to or it doesn't exist! Check to see if it's on the Reward Item Table, what tier it is, and your spelling.''')
                                return start, dmChar

                            else:
                                # Converts number to ordinal - 1:1st, 2:2nd, 3:3rd...
                                # floor(n/10)%10!=1, this acts as an if statement to check if the number is in the teens
                                # (n%10<4), this acts as an if statement to check if the number is below 4
                                # n%10 get the last digit of the number
                                # by multiplying these number together we end up with calculation that will be 0 unless both conditions have been met, otherwise it is the digit
                                # this number x is then used as the starting point of the selection and ::4 will then select the second letter by getting the x+4 element
                                # technically it will get more, but since the string is only 8 characters it will return 2 characters always
                                # th, st, nd, rd are spread out by 4 characters in the string 
                                ordinal = lambda n: "%d%s" % (n,"tsnrhtdd"[(floor(n/10)%10!=1)*(n%10<4)*n%10::4])
                                # change the query to be an accurate representation
                                query = f"Spell Scroll ({ordinal(sRecord['Level'])} Level)"
                        
   
                        # search for the item in the DB with the function from bfunc
                        # this does disambiguation already so if there are multiple results for the item they will have already selected which one specifically they want
                        rewardConsumable, charEmbed, charEmbedmsg = await callAPI(ctx, charEmbed, charEmbedmsg ,'rit',query, tier=tierNum) 
                    
                        #if no item could be found, return the unchanged parameters and inform the user
                        if not rewardConsumable:
                            if not resume:
                                await ctx.channel.send(f'**{query}** does not seem to be a valid reward item.')
                            return start, dmChar
                        else:
                           
                            rewardConsumable_group_type = "Name"
                            if "Grouped" in rewardConsumable:
                               rewardConsumable_group_type = "Grouped"
                            
                            # check if the item has already been rewarded to the player
                            if (rewardConsumable[rewardConsumable_group_type] in dmChar[5][1][player_type]["Major"] or
                                rewardConsumable[rewardConsumable_group_type] in dmChar[5][1][player_type]["Minor"] or
                                rewardConsumable[rewardConsumable_group_type] in blocking_list_additions["Major"] or
                                rewardConsumable[rewardConsumable_group_type] in blocking_list_additions["Minor"]):
                                # inform the user of the issue
                                if not resume:
                                    await ctx.channel.send(f"You cannot award the more than one of the same reward item. Please choose a different reward item.")
                                # return unchanged parameters
                                return start, dmChar 
                            # check if the Tier of the item is appropriate
                            if int(rewardConsumable['Tier']) > tierNum:
                                if not resume:
                                    if rewardUser == dmChar[0]:
                                        await ctx.channel.send(f"You cannot award yourself this reward item because it is above your character's tier.")
                                    else:
                                        await ctx.channel.send(f"You cannot award this reward item because it is above the character's tier.")
                                # return unchanged parameters
                                return start, dmChar 
                            # if the item is rewarded to the DM and they are not allowed to pick a consumable
                            # and the item is neither minor nor consumable
                            if dmMnc and rewardUser == dmChar[0] and (rewardConsumable['Minor/Major'] != 'Minor' or  rewardConsumable["Type"] != "Magic Items"):
                                if not resume:
                                    await ctx.channel.send(f"You cannot award yourself this reward item because your reward item has to be a Minor Non-Consumable.")
                                # return unchanged parameters
                                return start, dmChar 
                                
                            # increase the appropriate counters based on what the reward is and who is receiving it
                            if rewardConsumable['Minor/Major'] == 'Minor':
                                if rewardUser == dmChar[0]:
                                    dmMinor += 1
                                else:
                                    minor += 1
                            elif rewardConsumable['Minor/Major'] == 'Major':
                                if rewardUser == dmChar[0]:
                                    dmMajor += 1
                                else:
                                    major += 1
                            
                            # set up error messages based on the allowed item counts inserted appropriately
                            rewardMajorErrorString = f"You cannot award any more **Major** reward items.\nTotal rewarded so far:\n**({major-len(blocking_list_additions['Major'])-1}/{rewardMajorLimit})** Major Rewards \n**({minor-len(blocking_list_additions['Minor'])}/{rewardMinorLimit-rewardMajorLimit})** Minor Rewards"
                            rewardMinorErrorString = f"You cannot award any more **Minor** reward items.\nTotal rewarded so far:\n**({major-len(blocking_list_additions['Major'])}/{rewardMajorLimit})** Major Rewards \n**({minor-len(blocking_list_additions['Minor'])-1}/{rewardMinorLimit-rewardMajorLimit})** Minor Rewards"

                            if rewardUser == dmChar[0]:
                                if chooseOr:
                                    if dmMajor > dmMajorLimit or (dmMinor+dmMajor) > dmMinorLimit:
                                        if not resume:
                                            await ctx.channel.send(f"You cannot award yourself any more Major or Minor reward items {dmMajor- len(blocking_list_additions['Major'])}/{dmMajorLimit}.")
                                        return start, dmChar 
                                else:
                                    if dmMajor > dmMajorLimit:
                                        if not resume:
                                            await ctx.channel.send(f"You cannot award yourself any more Major reward items {dmMajor - len(blocking_list_additions['Major'])}/{dmMajorLimit}.")
                                        return start, dmChar 
                                    elif dmMinor+dmMajor > dmMinorLimit:
                                        if not resume:
                                            await ctx.channel.send(f"You cannot award yourself any more Minor reward items {dmMinor - len(blocking_list_additions['Minor'])}/{dmMinorLimit}.")
                                        return start, dmChar 
                            
                            else:
                                if (major > rewardMajorLimit or (major+minor)>rewardMinorLimit):
                                    if not resume:
                                        if rewardConsumable['Minor/Major'] == 'Major':
                                            await ctx.channel.send(rewardMajorErrorString)
                                        else:
                                            await ctx.channel.send(rewardMinorErrorString)
                                        return start, dmChar
                                
                            # If it is a spell scroll, since we search for spells, we need to adjust the name
                            # WEIRD
                            # query has already been adjusted to work as an appropriate name
                            # this consumable name does not include the spell level that was calculated there
                            blocking_list_additions[rewardConsumable['Minor/Major']].append(rewardConsumable[rewardConsumable_group_type])

                            # the only reward items that are non-consumable are minors
                            # non-consumables don't have the Consumable property
                            if rewardConsumable['Minor/Major'] == 'Major':
                                awarded_majors.append(rewardConsumable['Name'])
                            else:
                                awarded_minors.append(rewardConsumable['Name'])
                            if 'spell scroll' in query.lower():
                                rewardConsumable['Name'] = f"Spell Scroll ({sRecord['Name']})"
                            
                            character_add[rewardConsumable["Type"]].append(rewardConsumable["Name"])
                    
                    # update the players consumable/item list with the rewarded consumable/item respectively
                    
                        
                    item_list = awarded_majors+awarded_minors
                    item_list_with_pluses = list(map(lambda s: "+"+s, item_list))
                    item_list_string = ", ".join(item_list)
                    if currentItem[2] == ["None"]:
                        currentItem[2] = item_list_with_pluses
                    else:
                        currentItem[2] += item_list_with_pluses
                    
                    # add all awarded items to the players reward tracker
                    for key, items in character_add.items():
                    
                        if(key == "Magic Items"):
                            currentItem[4][key] += items
                        else:
                            currentItem[4][key]["Add"] += items
                    
                    # update dmChar to track the rewarded item counts properly
                    dmChar[5][1][player_type]["Major"] += blocking_list_additions["Major"]
                    dmChar[5][1][player_type]["Minor"] += blocking_list_additions["Minor"]
                    # on completion inform the users that of the success and of the current standings with rewards
                    if not resume:
                        await ctx.channel.send(content=f"You have awarded ***{rewardUser.display_name}*** the following reward items: **{item_list_string}**.\n```Total rewarded so far:\n({major}/{rewardMajorLimit}) Major Reward Items\n({minor}/{rewardMinorLimit-rewardMajorLimit}) Minor Reward Items\n({dmMajor}/{dmMajorLimit}) DM Major Reward Items\n({dmMinor}/{dmMinorLimit-dmMajorLimit}) DM Minor Reward Items```")
                    
                else:
                    if not resume:
                        await ctx.channel.send(content=f"***{rewardUser}*** is not on the timer to receive rewards.")
            return start, dmChar
    """
    This command gets invoked by duringTimer and resume
    user -> Member object when passed in which makes the string label confusing
    start -> a dictionary of duration strings and player entry lists
    msg -> the message that caused the invocation, used to find the name of the character being added
    dmChar -> player entry of the DM of the game
    user -> the user being added, required since this command is invoked by add as well where the author is not the user necessarily
    resume -> used to indicate if this was invoked by the resume process where the messages are being retraced
    """
    @timer.command()
    async def addme(self,ctx, *, role="", msg=None, start="", user="", dmChar=None, resume=False, ):
        if ctx.invoked_with == 'prep' or ctx.invoked_with == 'resume':
            startcopy = start.copy()
            # user found is used to check if the user can be found in one of the current entries in start
            userFound = False
            # the key string where the user was found
            timeKey = ""
            # the user to add
            addUser = user
            channel = ctx.channel

            # Check if the player that will be added will exceed the player limit
            playerCount = 0
            playerLimit = 7
            for sk, sv in startcopy.items():
                playerCount += len(sv)

            
                
            # make sure that only the the relevant user can respond
            def addMeEmbedCheck(r, u):
                sameMessage = False
                if addEmbedmsg.id == r.message.id:
                    sameMessage = True
                return sameMessage and ((str(r.emoji) == '✅') or (str(r.emoji) == '❌')) and (u == dmChar[0])
            
            
            # if this command was invoked by during the resume process we need to take the time of the message
            # otherwise we take the current time
            if not resume:
                startTime = time.time()
            else:
                startTime = msg.created_at.replace(tzinfo=timezone.utc).timestamp()
            
            
            # we go over every key value pair in the start dictionary
            # u is a string of format "{Tier} (Friend Partial or Full) Rewards: {duration}" and v is a list player entries [member, char DB entry, consumables, char id]
            for u, v in startcopy.items():
                # loop over all entries in the player list and check if the addedUser is one of them
                for item in v:
                    if item[0] == addUser:
                        userFound = True
                        # the key of where the user was found
                        timeKey = u
                        break
            # if we didnt find the user we now need to the them to the system
            if not userFound:
                
                if addUser == dmChar[0]:
                    role = "DM"
                
                elif playerCount + 1 > playerLimit:
                    await channel.send(f'You cannot add more than {playerLimit} players to the timer.')
                    return start
                
                # first we invoke the signup command
                # no character is necessary if there are no rewards
                # this will return a player entry
                if role != "":
                    userInfo =  await ctx.invoke(self.timer.get_command('signup'), role=role, char=msg, author=addUser, resume=resume) 
                else:
                    userInfo =  await ctx.invoke(self.timer.get_command('signup'), role=role, char=None, author=addUser, resume=resume) 
                # if a character was found we then can proceed to setup the timer tracking
                if userInfo:
                    # if this is not during the resume phase then we cannot afford to do user interactions
                    if not resume:
                        
                        # create an embed object for user communication
                        addEmbed = discord.Embed()
                        if role != "":
                            # get confirmation to add the character to the game
                            addEmbed.title = f"Add ***{userInfo[1]['Name']}*** to timer?"
                            addEmbed.description = f"***{addUser.mention}*** is requesting their character to be added to the timer.\n***{userInfo[1]['Name']}*** - Level {userInfo[1]['Level']}: {userInfo[1]['Race']} {userInfo[1]['Class']}\nConsumables: {', '.join(userInfo[2])}\n\n✅: Add to timer\n\n❌: Deny"
                        else:
                            # get confirmation to add the player to the game
                            addEmbed.title = f"Add ***{userInfo[0].display_name}*** to timer?"
                            addEmbed.description = f"***{addUser.mention}*** is requesting to be added to the timer.\n\n✅: Add to timer\n\n❌: Deny"
                        # send the message to communicate with the DM and get their response
                        # ping the DM to get their attention to the message
                        addEmbedmsg = await channel.send(embed=addEmbed, content=dmChar[0].mention)
                        await addEmbedmsg.add_reaction('✅')
                        await addEmbedmsg.add_reaction('❌')

                        try:
                            # wait for a response from the user
                            tReaction, tUser = await self.bot.wait_for("reaction_add", check=addMeEmbedCheck , timeout=60)
                        # cancel when the user doesnt respond within the timefram
                        except asyncio.TimeoutError:
                            await addEmbedmsg.delete()
                            await channel.send(f'Timer addme cancelled. Try again using the following command:\n```yaml\n{commandPrefix}timer addme "character name" "consumable1, consumable2, [...]"```')
                            # cancel this command and avoid things being added to the timer
                            return start
                        else:
                            await addEmbedmsg.clear_reactions()
                            # cancel if the DM wants to deny the user
                            if tReaction.emoji == '❌':
                                await addEmbedmsg.edit(embed=None, content=f"Request to be added to timer denied.")
                                await addEmbedmsg.clear_reactions()
                                # cancel this command and avoid things being added to the timer
                                return start
                            await addEmbedmsg.edit(embed=None, content=f"I've added ***{addUser.display_name}*** to the timer.")
                    
                    if dmChar[0] == addUser:
                        dmChar[5][1]["DM"]["Major"].clear()
                        dmChar[5][1]["DM"]["Minor"].clear()
                        userInfo.append(dmChar[5])
                        dmChar.clear()
                        dmChar.extend(userInfo)
                    else:
                        # since the timer has already been going when this user is added it has to be partial rewards
                        # the plus indicates that the character is added
                        start[f"+Partial Rewards:{startTime}"] = [userInfo]
                else:
                    pass
            # the following are the case where the player has already been on the timer
            # % indicates that the character died
            # + in a partial rewards entry means that the character is on the timer
            elif '+' in timeKey or 'Full Rewards' in timeKey or 'No Rewards' in timeKey:
                if not resume:
                    await channel.send(content='Your character has already been added to the timer.')
            # - in a partial rewards entry means that the player was removed
            elif timeKey.startswith('-') or timeKey.startswith('%'):
                # avoid messages if in resume stage
                if not resume:
                    await channel.send(content='You have been re-added to the timer.')
                # create a new entry with the same value as the one being replaced
                # this doesnt affect multiple players because the timestamp is hopefully preciese enough that no two players could have been removed at the same time
                # this invariant holds because this action could not be done if a player were part of the Full Rewards section 
                #   which is the only element where there will be multiple player entries
                # this attaches the starting time of this readd and separates is with a ':' 
                if(timeKey.startswith('%')):
                    start[f"{timeKey.replace('%', '+')}:{startTime}"] = start[timeKey]
                else:
                    start[f"{timeKey.replace('-', '+')}:{startTime}"] = start[timeKey]
                # delete the current entry
                del start[timeKey]
            
            else:
                # if the player was found in the dictionary, and the entries did not include any of the above the something was messed up
                if not resume:
                    await ctx.channel.send(content=f"I cannot find any mention of the user you are trying to add. Please check your format and spelling.")
            return start
    """
    This command is used to add players to the prep list or the running timer
    The code for adding players to the timer has been refactored into 'addme' and here just limits the addition to only one player
    prep does not pass in any value for 'start' but prep = True
    There is an important distinction between checking for invoked_with == 'prep' and prep = True
    the former would not be true if the resume command was used, but the prep property still allows to differentiate between the two stages
    This command returns two different values, if called during the prep stage then the member object of the player is returned, otherwise it is a dictionary as explained in duringTimer startTimes
    msg -> the message that caused the invocation of this command
    start-> this is a confusing variable, if this is called during prep it is returned as a member object and no value is passed in
        if called during resume than it is a timer dictionary as described in duringTimer startTimes
        this works because in that specific case start will be returned
    """
    @timer.command()
    async def add(self,ctx, *, msg, role="", start=None,prep=None, resume=False):
        if ctx.invoked_with == 'prep' or ctx.invoked_with == 'resume':
            guild = ctx.guild
            #if normal mentions were used then no users would have to be gotten later
            addList = msg.mentions
            addUser = None
            # limit adds to only one player at a time
            if len(addList) > 1:
                await ctx.channel.send(content=f"I cannot add more than one player! Please try the command with one player and check your format and spelling.")
                return None
            # if there was no player added
            elif addList == list():
                await ctx.channel.send(content=f"You forgot to mention a player! Please try the command again and ping the player.")
                return None
            else:
                # get the first ( and only ) mentioned user 
                addUser = addList[0]
                # if this was done during the prep phase then we only need to return the user
                if prep:
                    return addUser
                # in the duringTimer stage we need to add them to the timerDictionary instead
                # the dictionary gets manipulated directly which affects all versions
                else:
                    #otherwise we need to add the user properly to the timer and perform the setup
                    await ctx.invoke(self.timer.get_command('addme'), role=role, start=start, msg=msg, user=addUser, resume=resume) 
            return start
    
    async def addDuringTimer(self,ctx, *, msg, role="", start=None,resume=False, dmChar=None, ):
        if ctx.invoked_with == 'prep' or ctx.invoked_with == 'resume':
            guild = ctx.guild
            #if normal mentions were used then no users would have to be gotten later
            addList = msg.mentions
            addUser = None
            # limit adds to only one player at a time
            if len(addList) > 1:
                await ctx.channel.send(content=f"I cannot add more than one player! Please try the command with one player and check your format and spelling.")
                return None
            # if there was no player added
            elif addList == list():
                await ctx.channel.send(content=f"You forgot to mention a player! Please try the command again and ping the player.")
                return None
            else:
                # get the first ( and only ) mentioned user 
                addUser = addList[0]
                # in the duringTimer stage we need to add them to the timerDictionary instead
                # the dictionary gets manipulated directly which affects all versions
                #otherwise we need to add the user properly to the timer and perform the setup
                await ctx.invoke(self.timer.get_command('addme'), role=role, start=start, msg=msg, user=addUser, resume=resume, dmChar=dmChar) 
            return start

    @timer.command()
    async def removeme(self,ctx, msg=None, start="",role="",user="", resume=False, death=False):
        if ctx.invoked_with == 'prep' or ctx.invoked_with == 'resume':
            startcopy = start.copy()
            
            # user found is used to check if the user can be found in one of the current entries in start
            userFound = False
            # look through
            for u, v in startcopy.items():
                for item in v:
                    if item[0] == user:
                        # the key of where the user was found
                        userFound = u
                        # the player entry of the user
                        userInfo = item
            
            # if this command was invoked by during the resume process we need to take the time of the message
            # otherwise we take the current time
            if not resume:
                endTime = time.time()
            else:
                endTime = msg.created_at.replace(tzinfo=timezone.utc).timestamp()
            
            # if no entry could be found we inform the user and return the unchanged state
            if not userFound:
                if not resume:
                    await ctx.channel.send(content=f"***{user}***, I couldn't find you on the timer to remove you.") 
                return start
            # checks if the last entry was because of a death (%) or normal removal (-)
            if '-' in userFound or '%' in userFound: 
                # since they have been removed last time, they cannot be removed again
                if not resume:
                    await ctx.channel.send(content=f"You have already been removed from the timer.")  
            
            # if the player has been there the whole time
            elif 'Full Rewards' in userFound or 'No Rewards' in userFound:
                # remove the player entry from the list of entries
                start[userFound].remove(userInfo)
                if death:
                    # if the removal is because of a death we mark it with %
                    # The string separates the list of start and end times by :
                    # since this is the first occurence there will only be one entry
                    # efficincy can be gained by limiting it to 1 split because of this invariant
                    # since this is the first entry we need to specifically add the player entry since the current position is a list of them
                    start[f"%Partial Rewards:{userFound.split(':')[1]}?{endTime}"] = [userInfo]
                else:
                    # otherwise we use the standard -
                    start[f"-Partial Rewards:{userFound.split(':')[1]}?{endTime}"] = [userInfo]
                if not resume:
                    await ctx.channel.send(content=f"***{user}***, you have been removed from the timer.")
            elif '+' in userFound:
                # update the timer marker appropriately and attach the end time to the new entry string
                # transfer the player entry and delete the old entry
                if  death:
                    start[f"{userFound.replace('+', '%')}?{endTime}"] = start[userFound]
                    del start[userFound]
                else:
                    start[f"{userFound.replace('+', '-')}?{endTime}"] = start[userFound]
                    del start[userFound]
                if not resume:
                    await ctx.channel.send(content=f"***{user}***, you have been removed from the timer.")

        return start

    @timer.command()
    async def death(self,ctx, msg, start="", role="", resume=False):
        if ctx.invoked_with == 'prep' or ctx.invoked_with == 'resume':
            await self.removeDuringTimer(ctx, msg, start=start, role=role, resume=resume, death=True)
    
    """
    This command is used to remover players from the prep list or the running timer
    The code for removing players from the timer has been refactored into 'removeme' and here just limits the addition to only one player
    prep does not pass in any value for 'start' but prep = True
    msg -> the message that caused the invocation of this command
    role-> which tier the character is
    start-> this would be clearer as a None object since the final return element is a Member object
    death -> if the removal is because the character died in the game
    """
    @timer.command()
    async def remove(self,ctx, msg, start=None,role="", prep=False, resume=False, death=False):
        if ctx.invoked_with == 'prep' or ctx.invoked_with == 'resume':
            guild = ctx.guild
            removeList = msg.mentions
            removeUser = ""

            if len(removeList) > 1:
                await ctx.channel.send(content=f"I cannot remove more than one player! Please try the command with one player and check your format and spelling.")
                return None
            elif len(removeList) == 0:
                if not resume:
                    await ctx.channel.send(content=f"I cannot find any mention of the user you are trying to remove. Please check your format and spelling.")
            elif not removeList[0] in start:
                await ctx.channel.send(content=f"I cannot find the mentioned player in the roster.")
                return None
            else:
                removeUser = removeList[0]
                if prep:
                    return removeUser
                else:
                    await ctx.invoke(self.timer.get_command('removeme'), start=start, msg=msg, role=role, user=removeUser, resume=resume, death=death)
                
    async def removeDuringTimer(self,ctx, msg, start=None,role="", resume=False, death=False):
        if ctx.invoked_with == 'prep' or ctx.invoked_with == 'resume':
            guild = ctx.guild
            removeList = msg.mentions
            removeUser = ""

            if len(removeList) > 1:
                await ctx.channel.send(content=f"I cannot remove more than one player! Please try the command with one player and check your format and spelling.")
                return None

            elif removeList != list():
                removeUser = removeList[0]
                await ctx.invoke(self.timer.get_command('removeme'), start=start, msg=msg, role=role, user=removeUser, resume=resume, death=death)
            else:
                if not resume:
                    await ctx.channel.send(content=f"I cannot find any mention of the user you are trying to remove. Please check your format and spelling.")
            return start

    """
    the command used to display the current state of the game timer to the users
    start -> a dictionary of strings and player list pairs, the strings are made out of the kind of reward and the duration and the value is a list of players entries (format can be found as the return value in signup)
    game -> the name of the running game
    role -> the Tier of the game
    stamp -> the start time of the game
    author -> the Member object of the DM of the game
    """
    @timer.command()
    async def stamp(self,ctx, stamp=0, role="", game="", author="", start="", dmChar=[], embed="", embedMsg=""):
        if ctx.invoked_with == 'prep' or ctx.invoked_with == 'resume':
            # copy the duration trackers from the game
            startcopy = start.copy()
            user = author.display_name
            # calculate the total duration of the game so far
            end = time.time()
            duration = end - stamp
            durationString = timeConversion(duration)
            # reset the fields in the embed object
            embed.clear_fields()

            # fore every entry in the timer dictionary we need to perform calculations
            for key, value in startcopy.items():
                for v in value:
                    
                    consumablesString = ""
                    rewardsString = ""
                    # if the game were without rewards we would not have to check for consumables
                    if role != "":
                        if v[2] != ['None'] and v[2] != list():
                            # cList -> consumable list of the game
                            cList = []
                            # rList -> reward items of the game
                            rList = []

                            # go over every entry in the consumables list and add them appropriately
                            # reward items are indicated by a plus
                            for i in v[2]:
                                if i.startswith('+') and not i[1].isnumeric():
                                    rList.append(i)
                                else:
                                    cList.append(i)
                            # create the strings of the lists when appropriate
                            if cList != list():
                                consumablesString = "\nConsumables: " + ', '.join(cList)
                            if rList != list():
                                rewardsString = "\nRewards: " + ', '.join(rList)
                    # create field entries for every reward entry as appropriate
                    # - indicates that the entry is for people who were removed from the timer
                    # % indicates that a character died
                    if "Full Rewards" in key and not key.startswith("-") and not key.startswith("%"):
                        embed.add_field(name= f"**{v[0].display_name}**", value=f"{v[1]['Name']}{consumablesString}{rewardsString}", inline=False)
                    # if there are no rewards then we just need to list the player information
                    elif 'No Rewards' in key:
                        embed.add_field(name= f"**{v[0].display_name}**", value=f"{v[0].mention}", inline=False)
                    # if the player is removed from the timer we don't list them
                    elif key.startswith("-"):
                        pass
                    # list that the character died
                    elif key.startswith("%"):
                        embed.add_field(name= f"~~{v[0].display_name}~~", value=f"{v[1]['Name']} - **DEATH**{consumablesString}{rewardsString}", inline=False) 
                    else:
                        # if the player did not receive the full rewards then we need to add together all the time they have played
                        # these times are separated by : and formated as 'add time ? remove time'
                        durationEach = 0
                        timeSplit = (key + f'?{end}').split(':')
                        for t in range(1, len(timeSplit)):
                            ttemp = timeSplit[t].split('?')
                            # add the timer difference of the add and remove times to the sum
                            durationEach += (float(ttemp[1]) - float(ttemp[0]))

                        if role != "":
                            embed.add_field(name= f"**{v[0].display_name}** - {timeConversion(durationEach)} (Latecomer)\n", value=f"{v[1]['Name']}{consumablesString}{rewardsString}", inline=False)
                        else:
                            # if it is a no rewards game then there is no character to list
                            embed.add_field(name= f"**{v[0].display_name}** - {timeConversion(durationEach)} (Latecomer)\n", value=v[0].mention, inline=False)
            
            if(dmChar[1] != "No Rewards"):
                item_rewards = dmChar[4]["Inventory"]["Add"]+dmChar[4]["Consumables"]["Add"]+dmChar[4]["Magic Items"]
                dm_text =dmChar[1]["Name"]+ ("\nRewards:\n+"+"\n+".join(item_rewards))*(item_rewards != list())
                embed.add_field(name= f"**DM: {dmChar[0].display_name}**", value=dm_text, inline=False)
            # update the title of the embed message with the current time
            embed.title = f'**{game}**: {durationString}'
            msgAfter = False
            
            # we need separate advice strings if there are no rewards
            if role != "":
                stampHelp = f'```md\n[Player][Commands]\n# Adding Yourself\n   {commandPrefix}timer addme "character name" "consumable1, consumable2, [...]"\n# Using Items\n   - item\n# Removing Yourself\n   {commandPrefix}timer removeme\n\n[DM][Commands]\n# Adding Players\n   {commandPrefix}timer add @player "character name" "consumable1, consumable2, [...]"\n# Removing Players\n   {commandPrefix}timer remove @player\n# Awarding Reward Items\n   {commandPrefix}timer reward @player "reward item1, reward item2, [...]"\n# Revoking Reward Items\n   {commandPrefix}timer undo rewards\n# Stopping the Timer\n   {commandPrefix}timer stop```'
            else:
                stampHelp = f'```md\n[Player][Commands]\n# Adding Yourself\n   {commandPrefix}timer addme "character name" "consumable1, consumable2, [...]"\n# Using Items\n   - item\n# Removing Yourself\n   {commandPrefix}timer removeme\n\n[DM][Commands]\n# Adding Players\n   {commandPrefix}timer add @player "character name" "consumable1, consumable2, [...]"\n# Removing Players\n   {commandPrefix}timer remove @player\n# Awarding Reward Items\n   {commandPrefix}timer reward @player "reward item1, reward item2, [...]"\n# Revoking Reward Items\n   {commandPrefix}timer undo rewards\n# Stopping the Timer\n   {commandPrefix}timer stop```'
            # check if the current message is the last message in the chat
            # this checks the 1 message after the current message, which if there is none will return an empty list therefore msgAfter remains False
            async for message in ctx.channel.history(after=embedMsg, limit=1):
                msgAfter = True
            # if it is the last message then we just need to update
            if not msgAfter:
                await embedMsg.edit(embed=embed, content=stampHelp)
            else:
                # otherwise we delete the old message and resend the time stamp
                if embedMsg:
                    await embedMsg.delete()
                embedMsg = await ctx.channel.send(embed=embed, content=stampHelp)

            return embedMsg

    @timer.command(aliases=['end'])
    async def stop(self,ctx,*,start="", role="", game="", datestart="", dmChar="", guildsList="", ddmrw= False):
        if ctx.invoked_with == 'prep' or ctx.invoked_with == 'resume':
            end = time.time() + 3600 *0
            
            tierNum = 0
            guild = ctx.guild

            stopEmbed = discord.Embed()
            
            stopEmbed.set_footer(text=f"Placeholder, if this remains remember the wise words DO NOT PANIC and get a towel.")
            
            # turn Tier string into tier number
            if role == "Ascended":
                tierNum = 5
            elif role == "True":
                tierNum = 4
            elif role == "Elite":
                tierNum = 3
            elif role == "Journey":
                tierNum = 2
            elif role == "New":
                tierNum = 0
            elif role == "":
                # mark no reward games with a specific color
                stopEmbed.colour = discord.Colour(0xffffff)
            else:
                tierNum = 1
        
            deathChars = []
            
            # Session Log Channel
            logChannel = self.bot.get_channel(settingsRecord[str(ctx.guild.id)]["Sessions"])  # 728456783466725427 737076677238063125
            # logChannel = self.bot.get_channel(577227687962214406)
            
            
            dbEntry = {}
            dbEntry["Role"] = role
            dbEntry["Tier"] = tierNum
            dbEntry["Channel"] = ctx.channel.name
            dbEntry["End"] = end
            dbEntry["Game"] = game
            dbEntry["Status"] = "Processing"
            dbEntry["Players"] = {}
            
            dbEntry["DDMRW"] = settingsRecord["ddmrw"] or ddmrw
            if tierNum < 1:
                tierNum = 1
            rewardsCollection = db.rit
            rewardList = list(rewardsCollection.find({"Tier": tierNum}))
            rewardList_lower = list(rewardsCollection.find({"Tier": max(tierNum-1, 1)}))
            
            # go through the dictionary of times and calculate the rewards of every player
            for startItemKey, startItemValue in start.items():
                # duration of the play time of this entry
                duration = 0
                # list of players in this entry
                playerList = []
                # Attach the end time to the key temporarily for the calculations
                # This doubles up on the end time for people who were last removed from the timer, but since that calculation takes specifically the 1st and 2nd value, this 3rd element will not affect the calculations
                startItemsList = (startItemKey+ f'?{end}').split(':')
                
                # get the total duration
                if "Full Rewards" in startItemKey or  "No Rewards" in startItemKey:
                
                    starting_time = float(startItemsList[1].split('?')[0])
                    # since there is only one set of start and end times we know that startItemsList only has 2 elements
                    # first element is the reward type and the second contains the start and end time separated by ?
                    totalDurationTime = end - starting_time
                    # get the string to represent the duration in hours and minutes
                    totalDuration = timeConversion(totalDurationTime)

                # this indicates that the character had died
                if '%' in startItemKey:
                    deathChars.append(startItemValue[0])
                
                # this indicates that the player had been removed from the timer at some point so we need to calculate each split
                if "?" in startItemKey:
                    # this starts at 1 since the first element contains no timestamp information
                    for t in range(1, len(startItemsList)):
                        ttemp = startItemsList[t].split('?')
                        duration += (float(ttemp[1]) - float(ttemp[0]))
                else:
                    # if the player was only there for one section we can skip the loop above
                    # WEIRD
                    # This adds code complexity in favor of saving the creation of the range above
                    ttemp = startItemsList[1].split('?')
                    duration = (float(ttemp[1]) - float(ttemp[0]))
                


                for value in startItemValue:
                    playerDBEntry={}
                    randomItems = [random.choice(rewardList).copy(), random.choice(rewardList_lower).copy()]
                    playerDBEntry["Double Items"] = []
                    for i in randomItems:
                        if("Grouped" in i):
                            i["Name"] = random.choice(i["Name"])
                        elif("Spell Scroll" in i["Name"]):
                            if("Cantrip" in i["Name"]):
                                spell_level = 0
                            else:
                                spell_level = [int(x) for x in i["Name"] if x.isnumeric()][0]
                            
                            spell_result = list(db.spells.aggregate([{ "$match": { "Level": spell_level } }, { "$sample": { "size": 1 } }]))[0]
                            i["Name"] = f"Spell Scroll ({spell_result['Name']})"
                        playerDBEntry["Double Items"].append([i["Type"], i["Name"]])
                    
                    playerDBEntry.update(value[4])
                    playerDBEntry["Status"] = "Alive"* (not (value in deathChars)) + "Dead"* (value in deathChars)
                    playerDBEntry["Character ID"] = value[1]["_id"]
                    playerDBEntry["Character Name"] = value[1]["Name"]
                    playerDBEntry["Level"] = value[1]["Level"]
                    if "Guild" in value[1]:
                        playerDBEntry["Guild"] = value[1]["Guild"]
                        playerDBEntry["2xR"] = True
                        playerDBEntry["2xI"] = True
                        playerDBEntry["Guild Rank"] = value[1]["Guild Rank"]
                    playerDBEntry["Character CP"] = value[1]["CP"]
                    playerDBEntry["Mention"] = value[0].mention

                    playerDBEntry["CP"] = (duration// 1800) / 2
                    # add the player to the list of completed entries
                    dbEntry["Players"][f"{value[0].id}"] = playerDBEntry
                    playerList.append(value)
            hoursPlayed = (totalDurationTime // 1800) / 2
            
            # if hoursPlayed < 0.5:
                # self.timer.get_command('prep').reset_cooldown(ctx)
                # await ctx.channel.send(content=f"The session was less than 30 minutes and therefore was not counted.")
                
                # return
            # check if the game has rewards
            if role != "":
                # post a session log entry in the log channel
                sessionMessage = await logChannel.send(embed=stopEmbed)
                await ctx.channel.send(f"The timer has been stopped! Your session log has been posted in the {logChannel.mention} channel. Write your session log summary in this channel by using the following command:\n```ini\n$session log {sessionMessage.id} [Replace the brackets and this text with your session summary log.]```")

                stopEmbed.set_footer(text=f"Game ID: {sessionMessage.id}")
                modChannel = self.bot.get_channel(settingsRecord[str(ctx.guild.id)]["Mod Logs"])
                modEmbed = discord.Embed()
                modEmbed.description = f"""A one-shot session log was just posted for {ctx.channel.mention}.

DM: {dmChar[0].mention} 
Game ID: {sessionMessage.id}
Link: {sessionMessage.jump_url}

React with :construction: if a summary log has not yet been appended by the DM.
React with :pencil: if you messaged the DM to fix something in their summary log.
React with ✅ if you have approved the session log.
React with :x: if you have denied the session log.
React with :classical_building: if you have denied one of the guilds.

Reminder: do not deny any session logs until we have spoken about it as a team."""

                modMessage = await modChannel.send(embed=modEmbed)
                for e in ["🚧", "📝", "✅", "❌", "🏛️"]:
                    await modMessage.add_reaction(e)    
                
            
            dbEntry["Start"] = starting_time
            
            dbEntry["Log ID"] = sessionMessage.id
            
            stopEmbed.title = f"Timer: {game} [END] - {totalDuration}"
            stopEmbed.description = """**General Summary**:
• Give context to pillars and guild quest guidelines.
• Focus on the outline of quest and shouldn't include "fluff".
• Should help Mods understand context of the one-shot.

In order to help determine if the adventurers fulfilled a pillar or a guild's quest guidelines, ask yourself the following questions:

**Exploration**
• Did they deal with environmental effects? How did they resolve them?
• Did they interact the environment to gather info and make informed decisions? What were the clues? How did these contribute to their success?
• Did they travel or solve a puzzle/trap within a limited time frame? What problems did they have to face? How were they solved?
• How did any unsuccessful attempts negatively affect future events?

**Social**
• Did they change an NPC's attitude? How did they do it and why was it important?
• Did they convince an NPC of something against their nature or traits? Why was it important?
• Did they retrieve info from an NPC? How did they retrieve it? Was it relevant to the main objective?
• How did any unsuccessful attempts negatively affect future events?

**Combat**
• Did they fight? What kind of creatures?
• Did they engage in combat as a result of unsuccessful attempts in the Exploration or Social pillars?
• Did combat present complications for future events?

**Guilds**
• How were guilds central to plot and setting, main objectives, core elements, and overall progression of your one-shot?
• Which guidelines were fulfilled and how?
• If guidelines were not fulfilled, how/why did the party fail?
""" 
            
            
            
            # get the collections of characters
            playersCollection = db.players
            logCollection = db.logdata
            # and players
            usersCollection = db.users

            # Noodles Math
            # get the user record of the DM
            uRecord  = usersCollection.find_one({"User ID": str(dmChar[0].id)})
            noodles = 0
            # get the total amount of minutes played
            
            #DM REWARD MATH STARTS HERE
            dmDBEntry = {}
            if(dmChar[1]!="No Rewards"):
                dm_char_level = dmChar[1]["Level"]
                if dm_char_level < 5:
                    dm_tier_num = 1
                elif dm_char_level < 11:
                    dm_tier_num = 2
                elif dm_char_level < 17:
                    dm_tier_num = 3
                elif dm_char_level < 20:
                    dm_tier_num = 4
                else:
                    dm_tier_num = 5
                    
                value = dmChar
                rewardList = list(rewardsCollection.find({"Tier": dm_tier_num}))
                rewardList_lower = list(rewardsCollection.find({"Tier": max(dm_tier_num -1,1)}))
                randomItems = [random.choice(rewardList), random.choice(rewardList_lower)]
                
                dmDBEntry["Double Items"] = []
                
                for i in randomItems:
                    if("Grouped" in i):
                        i["Name"] = random.choice(i["Name"])
                    elif("Spell Scroll" in i["Name"]):
                        if("Cantrip" in i["Name"]):
                            spell_level = 0
                        else:
                            spell_level = [int(x) for x in i["Name"] if x.isnumeric()][0]
                        
                        spell_result = list(db.spells.aggregate([{ "$match": { "Level": spell_level } }, { "$sample": { "size": 1 } }]))[0]
                        i["Name"] = f"Spell Scroll ({spell_result['Name']})"
                    dmDBEntry["Double Items"].append([i["Type"], i["Name"]])
                dmDBEntry.update(value[4])
                dmDBEntry["Character ID"] = value[1]["_id"]
                dmDBEntry["Character Name"] = value[1]["Name"]
                dmDBEntry["Level"] = value[1]["Level"]
                if "Guild" in value[1]:
                    dmDBEntry["Guild"] = value[1]["Guild"]
                    dmDBEntry["2xR"] = True
                    dmDBEntry["2xI"] = True
                    dmDBEntry["Guild Rank"] = value[1]["Guild Rank"]
                dmDBEntry["Character CP"] = value[1]["CP"]
                dmDBEntry["DM Double"] = dbEntry["DDMRW"]
                playerList.append(value)
                    
            dmDBEntry["ID"] = str(dmChar[0].id)
            dmDBEntry["Mention"] = dmChar[0].mention
            n=0
            if uRecord and "Noodles" in uRecord:
                n = uRecord["Noodles"]
            dmDBEntry["Noodles"] = n
            dmDBEntry["CP"] = hoursPlayed
            
            dbEntry["DM"] = dmDBEntry
            
            dbEntry["Guilds"] = {}
            
            # if the game received rewards
            if role != "": 
                # get the db collection of guilds and set up variables to track relevant information
                guildsCollection = db.guilds
                # if a member of the guild was in the game
                guildMember = False
                # list of all guild records that need to be update, with the updates applied
                guildsRecordsList = list()
                
                # passed in parameter, check if there were guilds involved
                if guildsList != list():
                    # for every guild in the game
                    for g in guildsList:
                        # get the DB record of the guild
                        gRecord  = guildsCollection.find_one({"Channel ID": str(g.id)})
                        if not gRecord:
                            continue
                        guildDBEntry = {}
                        guildDBEntry["Status"] = True
                        guildDBEntry["Rewards"] = False
                        guildDBEntry["Items"] = False
                        guildDBEntry["Drive"] = False
                        guildDBEntry["Mention"] = g.mention
                        guildDBEntry["Name"] = gRecord["Name"]
                        
                        dbEntry["Guilds"][gRecord["Name"]] = guildDBEntry
                        
                        # if the guild exists in the DB
                # create a list of of UpdateOne objects from the data entries for the bulk_write
                timerData = list(map(lambda item: UpdateOne({'_id': item[3]}, {"$set": {"GID": dbEntry["Log ID"]}}), playerList))
                

                # try to update all the player entries
                try:
                    playersCollection.bulk_write(timerData)

                    logCollection.insert_one(dbEntry)
                except BulkWriteError as bwe:
                    print(bwe.details)
                    # if it fails, we need to cancel and use the error details
                    charEmbedmsg = await ctx.channel.send(embed=None, content="Uh oh, looks like something went wrong. Please try the timer again.")
                    return
                await sessionMessage.edit(embed=stopEmbed)

                try:
                    # create a bulk write entry for the players
                    usersData = list(map(lambda item: UpdateOne({'User ID':str(item[0].id) }, {'$set': {'User ID':str(item[0].id) }}, upsert=True), playerList))
                    usersCollection.bulk_write(usersData)
                except BulkWriteError as bwe:
                    print(bwe.details)
                    charEmbedmsg = await ctx.channel.send(embed=None, content="Uh oh, looks like something went wrong. Please try the timer again.")
                except Exception as e:
                    print ('MONGO ERROR: ' + str(e))
                    charEmbedmsg = await ctx.channel.send(embed=None, content="Uh oh, looks like something went wrong. Please try the timer again.")
                else:
                    print('Success')
                await generateLog(self, ctx, dbEntry["Log ID"], sessionInfo = dbEntry)
            
            
            # enable the starting timer commands
            self.timer.get_command('prep').reset_cooldown(ctx)

        return

    @timer.command()
    @commands.has_any_role('Mod Friend', 'A d m i n')
    async def list(self,ctx):
        if not currentTimers:
            currentTimersString = "There are currently NO timers running!"
        else:
            currentTimersString = "There are currently timers running in these channels:\n"
        for i in currentTimers:
            currentTimersString = f"{currentTimersString} - {i} \n"
        await ctx.channel.send(content=currentTimersString)

    @timer.command()
    @commands.has_any_role('Mod Friend', 'A d m i n')
    async def resetcooldown(self,ctx):
        self.timer.get_command('prep').reset_cooldown(ctx)
        await ctx.channel.send(f"Timer has been reset in #{ctx.channel}")
    
    
    # """
    # This function is used to restart a timer that was interruped by an error
    # """
    # @commands.cooldown(1, float('inf'), type=commands.BucketType.channel) 
    # @timer.command()
    # #TODO: cmapaign resume timer
    # async def resume(self,ctx):
        # if not self.timer.get_command('prep').is_on_cooldown(ctx):
            # # check for messages from a bot
            # def predicate(message):
                # return message.author.bot and message.author.id == self.bot.user.id

            # channel=ctx.channel
            # # make sure that the channel is a game channel
            # if str(channel.category).lower() not in gameCategory:
                # if "no-context" in channel.name or "secret-testing-area" or  "bot2-testing" in channel.name:
                    # pass
                # else:
                    # await channel.send('Try this command in a game room channel!')
                    # return
            # # make sure that there is no timer running right now
            # if self.timer.get_command('prep').is_on_cooldown(ctx):
                # await channel.send(f"There is already a timer that has started in this channel! If you started this timer, use the following command to stop it:\n```yaml\n{commandPrefix}timer stop```")
                # return

            # timerCog = self.bot.get_cog('Timer')
            # # set up the global timer tracker variable
            # global currentTimers
            # author = ctx.author
            # resumeTimes = {}
            # timerMessage = None
            # guild = ctx.guild
            
            # # find every message by a bot in the last 200 messages in the channel
            # async for message in ctx.channel.history(limit=200).filter(predicate):
                # # if there was a message of a timer being started we need to simulate the runtime of the timer
                # # this if statement breaks after its execution so it only executes once
                # # the default ordering of the history is newest first so this assures that only the latest timer gets restarted
                # if "Starting the timer." in message.content:
                    # timerMessage = message
                    # # get the first line of the timer by splitting at the first newline and getting the first element
                    # startString = (timerMessage.content.split('\n', 1))[0]
                    # # extract the tier name, it is formated as ({Tier name} Friend)
                    # startRole = re.search('\(([^)]+)', startString)
                    # # if there was no role, then it was a no rewards game
                    # if startRole is None:
                        # startRole = ''
                    # else: 
                        # # separate the role name from 'friend'
                        # startRole = startRole.group(1).split()[0]
                    # # the game name is bolded, which in discord is done by going **x**
                    # startGame = re.search('\*\*(.*?)\*\*', startString).group(1)
                    # # get the original start time
                    # startTimerCreate = timerMessage.created_at
                    # startTime = startTimerCreate.replace(tzinfo=timezone.utc).timestamp()
                    # # establish the timer dictionary 
                    # resumeTimes = {f"{startRole} Friend Rewards":startTime}
                    # # get the start time as a formatted string
                    # datestart = startTimerCreate.replace(tzinfo=timezone.utc).astimezone(tz=pytz.timezone(timezoneVar)).strftime("%b-%d-%y %I:%M %p") 
                    
                    # # Search through the 10 messages before a starting timer and copy over all the fields in their embeds
                    # async for m in ctx.channel.history(before=timerMessage, limit=10):
                        
                        # if m.embeds:
                            # commandMessage = m
                            # commandEmbed = (m.embeds[0].to_dict())
                            # commandMessage.content += commandEmbed['description']

                            # resumeString=[]
                            # guildsList = commandMessage.channel_mentions
                            # # take the fields from the embed fields and add them to the dictionary
                            # for f in commandEmbed['fields']:
                                # if 'DM' in f['name'] or '<@' in f['value']:
                                    # resumeString.append(f"{f['name']}={f['value']}")
                            # commandMessage.content = ', '.join(resumeString)
                        # # if the timer was started, then grab all players that were there at the beginning
                        # if m.content == f'{commandPrefix}timer start' or m.content == f'{commandPrefix}t start':
                            # playerResumeList = [m.author.id] + commandMessage.raw_mentions
                            # author = m.author
                            # break

                    # start = []

                    # playersCollection = db.players
                    # # if the game has rewards being given then we need to grab the consumables players are bringing with them
                    # if "norewards" not in commandMessage.content and startRole: 
                        # # userList = re.search('"([^"]*)"', commandMessage).group(1).split(',')
                        # playerInfoList = commandMessage.content.split(',')
                        # for p in range (len(playerResumeList)):
                            # pTemp = []
                            # pConsumables = ['None']
                            # pTemp.append(guild.get_member(int(playerResumeList[p])))
                            # if p == 0:
                                # pName = playerInfoList[p].split(' will receive DM rewards')[0].split('=')[1].replace("*", "")
                               
                            # else:
                                # pName = playerInfoList[p].split('=')[0].replace("*", "")

                            # cRecord  = list(playersCollection.find({"User ID": str(playerResumeList[p]), "Name": {"$regex": pName.strip(), '$options': 'i' }}))

                            # if p > 0:
                                # pConsumables = playerInfoList[p].split('Consumables: ')[1].split(',')
                                # pTemp += [cRecord[0],pConsumables,cRecord[0]['_id']]
                                # start.append(pTemp)
                            # else:
                                # pTemp += [cRecord[0],pConsumables,cRecord[0]['_id']] 
                                # dmChar = pTemp
                                # dmChar.append(['Junior Noodle',{"Players" : [], "DM" :  []}])

                                # # find the name of which noodle role the DM has
                                # for r in dmChar[0].roles:
                                    # if 'Noodle' in r.name:
                                        # dmChar[5][0] = r.name
                                        # break

                        # print(start)
                        # resumeTimes = {f"{startRole} Friend Full Rewards:{startTime}":start} 


                    # else: 
                        # resumeTimes = {f"No Rewards:{startTime}":start}
                    # # go through every message after the timer started and reemulate the behavior
                    # # error messages and menus are blocked however
                    # async for message in ctx.channel.history(after=timerMessage):
                        # if (f"{commandPrefix}timer add " in message.content or f"{commandPrefix}t add " in message.content) and not message.author.bot:
                            # resumeTimes = await ctx.invoke(self.timer.get_command('add'), start=resumeTimes, role=startRole, msg=message, resume=True)
                        # elif  (f"{commandPrefix}timer addme" in message.content or f"{commandPrefix}t addme" in message.content) and not message.author.bot and (message.content != f'{commandPrefix}timer addme' or message.content != f'{commandPrefix}t addme'):
                            # resumeTimes = await ctx.invoke(self.timer.get_command('addme'), start=resumeTimes, role=startRole, dmChar=dmChar, msg=message, user=message.author, resume=True) 
                        # elif ((f"{commandPrefix}timer removeme" in message.content or f"{commandPrefix}timer remove " in message.content) or (f"{commandPrefix}t removeme" in message.content or f"{commandPrefix}t remove " in message.content)) and not message.author.bot: 
                            # if f"{commandPrefix}timer removeme" in message.content or f"{commandPrefix}t removeme" in message.content:
                                # resumeTimes = await ctx.invoke(self.timer.get_command('removeme'), msg=message, start=resumeTimes, role=startRole, user=message.author, resume=True)
                            # elif f"{commandPrefix}timer remove " in message.content or f"{commandPrefix}t remove " in message.content:
                                # resumeTimes = await ctx.invoke(self.timer.get_command('remove'), msg=message, start=resumeTimes, role=startRole, resume=True)
                        # elif f"{commandPrefix}timer death" in message.content or f"{commandPrefix}t death" in message.content:
                            # resumeTimes = await ctx.invoke(self.timer.get_command('death'), msg=message, start=resumeTimes, role=startRole, resume=True) 
                        # elif message.content.startswith('-') and message.author != dmChar[0]: 
                            # resumeTimes = await ctx.invoke(self.timer.get_command('deductConsumables'), msg=message, start=resumeTimes, resume=True)
                        # elif (f"{commandPrefix}timer reward" in message.content or f"{commandPrefix}t reward" in message.content) and (message.author == author):
                            # resumeTimes,dmChar = await self.reward(ctx, msg=message, start=resumeTimes, dmChar=dmChar, resume=True)
                        # elif ("Timer has been stopped!" in message.content) and message.author.bot:
                            # await channel.send("There doesn't seem to be a timer to resume here... Please start a new timer!")
                            # return

                    # break

                    # print(resumeTimes)
            # # if no message could be found within the limit or there no embed object could be found to get information from
            # if timerMessage is None or commandMessage is None:
                # await channel.send("There is no timer in the last 200 messages. Please start a new timer.")
                # return
            # # inform the users that the timer was restarted
            # await channel.send(embed=None, content=f"I have resumed the timer for **{startGame}** ({startRole})." )
            # # add the timer to the tracker
            # currentTimers.append('#'+channel.name)
            
            # stampEmbed = discord.Embed()
            # stampEmbed.set_footer(text=f'#{ctx.channel}\n{commandPrefix}timer help for help with the timer.')
            # stampEmbed.set_author(name=f'DM: {author.display_name}', icon_url=author.avatar_url)
            # stampEmbedmsg = None

            # # resume normal timer operations
            # await timerCog.duringTimer(ctx, datestart, startTime, resumeTimes, startRole, startGame, author, stampEmbed, stampEmbedmsg,dmChar,guildsList)
            # # enable the command again
            # # after the timer finished, remove it from the tracker
            # currentTimers.remove('#'+channel.name)
        # else:
            # await ctx.channel.send(content=f"There is already a timer that has started in this channel! If you started this timer, use the following command to stop it:\n```yaml\n{commandPrefix}timer stop```")
            # return
    
    #extracted the checks to here to generalize the changes
    async def permissionCheck(self, msg, author):
        # check if the person who sent the message is either the DM, a Mod or a Admin
        if not (msg.author == author or "Mod Friend".lower() in [r.name.lower() for r in msg.author.roles] or "A d m i n s".lower() in [r.name.lower() for r in msg.author.roles]):
            await msg.channel.send(f'You cannot use this command!') 
            return False
        else: 
            return True
    
    """
    This functions runs continuously while the timer is going on and waits for commands to come in and then invokes them itself
    datestart -> the formatted date of when the game started
    startTime -> the specific time that the game started
    startTimes -> the dictionary of all the times that players joined and the player entries at that point (format of entries found in signup)
        the keys for startTimes are of the format "{Tier} (Friend Partial or Full) Rewards: {duration}"
        - in the key indicates a leave time
        % indicates a death
    role -> the tier of the game
    author -> person in control (normally the DM)
    stampEmbed -> the Embed object containing the information in regards to current timer state
    stampEmbedMsg -> the message containing stampEmbed
    dmChar -> the character of the DM 
    guildsList -> the list of guilds involved with the timer
    """
    async def duringTimer(self,ctx, datestart, startTime, startTimes, role, game, author, stampEmbed, stampEmbedmsg, dmChar, guildsList, ddmrw = False):
        # if the timer is being restarted then we create a new message with the stamp command
        if ctx.invoked_with == "resume":
            stampEmbedmsg = await ctx.invoke(self.timer.get_command('stamp'), stamp=startTime, role=role, game=game, author=author, start=startTimes, embed=stampEmbed, embedMsg=stampEmbedmsg)
        
        # set up the variable for the continuous loop
        timerStopped = False
        channel = ctx.channel
        user = author.display_name

        timerAlias = ["timer", "t"]

        #in no rewards games characters cannot die or get rewards
        if role != "":
            timerCommands = ['transfer', 'stop', 'end', 'add', 'remove', 'death', 'reward', 'stamp', 'undo rewards']
        else:
            timerCommands = ['transfer', 'stop', 'end', 'add', 'remove', 'stamp']

        timerCombined = []
        #create a list of all command an alias combinations
        for x in product(timerAlias,timerCommands):
            timerCombined.append(f"{commandPrefix}{x[0]} {x[1]}")
        
        #repeat this entire chunk until the stop command is given
        while not timerStopped:
            try:
                if role != "":
                    #the additional check for  '-' being only in games with a tier allows for consumables to be used only in proper games
                    msg = await self.bot.wait_for('message', timeout=60.0, check=lambda m: (any(x in m.content for x in timerCombined) or m.content.startswith('-')) and m.channel == channel)
                else:
                    msg = await self.bot.wait_for('message', timeout=60.0*15, check=lambda m: (any(x in m.content for x in timerCombined)) and m.channel == channel)
                #transfer ownership of the timer
                if (msg.content.startswith(f"{commandPrefix}timer transfer ") or msg.content.startswith(f"{commandPrefix}t transfer ")):
                    # check if the author of the message has the right permissions for this command
                    if await self.permissionCheck(msg, author):
                        #if the message had any mentions we take the first mention and transfer the timer to them
                        if msg.mentions and len(msg.mentions)>0:
                            author = msg.mentions[0]
                            # since they are already pinged during the command they are only referred to by their name
                            await channel.send(f'{author.display_name}, the current timer has been transferred to you. Use the following command to see a list of timer commands:\n```yaml\n{commandPrefix}timer help```')
                        else:
                            await channel.send(f'Sorry, I could not find a user in your message to transfer the timer.')
                # this is the command used to stop the timer
                # it invokes the stop command with the required information, explanations for the parameters can be found in the documentation
                # the 'end' alias could be removed for minimal efficiancy increases
                elif (msg.content == f"{commandPrefix}timer stop" or msg.content == f"{commandPrefix}timer end" or msg.content == f"{commandPrefix}t stop" or msg.content == f"{commandPrefix}t end"):
                    # check if the author of the message has the right permissions for this command
                    if await self.permissionCheck(msg, author):
                        
                        await ctx.invoke(self.timer.get_command('stop'), start=startTimes, role=role, game=game, datestart=datestart, dmChar=dmChar, guildsList=guildsList, ddmrw=ddmrw)
                        return

                # this behaves just like add above, but skips the ambiguity check of addme since only the author of the message could be added
                elif (msg.content.startswith(f"{commandPrefix}timer addme ") or msg.content.startswith(f"{commandPrefix}t addme ")) and '@player' not in msg.content and (msg.content != f'{commandPrefix}timer addme' or msg.content != f'{commandPrefix}t addme'):
                    # if the message author is the one who started the timer, call signup with the special DM moniker
                # the character is extracted from the message in the signup command 
                # special behavior:
                    startTimes = await ctx.invoke(self.timer.get_command('addme'), start=startTimes, role=role, msg=msg, user=msg.author, dmChar=dmChar)
                    stampEmbedmsg = await ctx.invoke(self.timer.get_command('stamp'), stamp=startTime, role=role, game=game, author=author, start=startTimes, dmChar=dmChar, embed=stampEmbed, embedMsg=stampEmbedmsg)
                # this invokes the add command, since we do not pass prep = True through, the special addme command will be invoked by add
                # @player is a protection from people copying the command
                elif (msg.content.startswith(f"{commandPrefix}timer add ") or msg.content.startswith(f"{commandPrefix}t add ")) and '@player' not in msg.content:
                    # check if the author of the message has the right permissions for this command
                    if await self.permissionCheck(msg, author):
                        # update the startTimes with the new added player
                        await self.addDuringTimer(ctx, start=startTimes, role=role, msg=msg, dmChar = dmChar)
                        # update the msg with the new stamp
                        stampEmbedmsg = await ctx.invoke(self.timer.get_command('stamp'), stamp=startTime, role=role, game=game, author=author, start=startTimes, dmChar=dmChar, embed=stampEmbed, embedMsg=stampEmbedmsg)
                # this invokes the remove command, since we do not pass prep = True through, the special removeme command will be invoked by remove
                elif msg.content == f"{commandPrefix}timer removeme" or msg.content == f"{commandPrefix}t removeme":
                    startTimes = await ctx.invoke(self.timer.get_command('removeme'), start=startTimes, role=role, user=msg.author)
                    stampEmbedmsg = await ctx.invoke(self.timer.get_command('stamp'), stamp=startTime, role=role, game=game, author=author, start=startTimes, dmChar=dmChar, embed=stampEmbed, embedMsg=stampEmbedmsg)
                elif (msg.content.startswith(f"{commandPrefix}timer remove ") or msg.content.startswith(f"{commandPrefix}t remove ")): 
                    if await self.permissionCheck(msg, author): 
                        await self.removeDuringTimer(ctx, msg, start=startTimes, role=role)
                        stampEmbedmsg = await ctx.invoke(self.timer.get_command('stamp'), stamp=startTime, role=role, game=game, author=author, start=startTimes, dmChar=dmChar, embed=stampEmbed, embedMsg=stampEmbedmsg)
                elif (msg.content.startswith(f"{commandPrefix}timer stamp") or msg.content.startswith(f"{commandPrefix}t stamp")): 
                    stampEmbedmsg = await ctx.invoke(self.timer.get_command('stamp'), stamp=startTime, role=role, game=game, author=author, start=startTimes, dmChar=dmChar, embed=stampEmbed, embedMsg=stampEmbedmsg)
                elif (msg.content.startswith(f"{commandPrefix}timer reward") or msg.content.startswith(f"{commandPrefix}t reward")):
                    if await self.permissionCheck(msg, author):
                        startTimes,dmChar = await self.reward(ctx, msg=msg, start=startTimes,dmChar=dmChar)
                elif (msg.content.startswith(f"{commandPrefix}timer death") or msg.content.startswith(f"{commandPrefix}t death")):
                    if await self.permissionCheck(msg, author):
                        await ctx.invoke(self.timer.get_command('death'), msg=msg, start=startTimes, role=role)
                        stampEmbedmsg = await ctx.invoke(self.timer.get_command('stamp'), stamp=startTime, role=role, game=game, author=author, dmChar=dmChar, start=startTimes, embed=stampEmbed, embedMsg=stampEmbedmsg)
                elif msg.content.startswith('-') and msg.author != dmChar[0]:
                    await ctx.invoke(self.timer.get_command('deductConsumables'), msg=msg, start=startTimes)
                    stampEmbedmsg = await ctx.invoke(self.timer.get_command('stamp'), stamp=startTime, role=role, game=game, author=author, start=startTimes, dmChar=dmChar, embed=stampEmbed, embedMsg=stampEmbedmsg)
                elif (msg.content.startswith(f"{commandPrefix}timer undo rewards") or msg.content.startswith(f"{commandPrefix}t undo rewards")):
                    # check if the author of the message has the right permissions for this command
                    if await self.permissionCheck(msg, author):
                        # update the startTimes with the new added player
                        await self.undoConsumables(ctx, msg, startTimes, dmChar)
                        # update the msg with the new stamp
                        stampEmbedmsg = await ctx.invoke(self.timer.get_command('stamp'), stamp=startTime, role=role, game=game, author=author, start=startTimes, dmChar=dmChar, embed=stampEmbed, embedMsg=stampEmbedmsg)

            except asyncio.TimeoutError:
                stampEmbedmsg = await ctx.invoke(self.timer.get_command('stamp'), stamp=startTime, role=role, game=game, author=author, start=startTimes, dmChar=dmChar, embed=stampEmbed, embedMsg=stampEmbedmsg)
            else:
                pass
               

def setup(bot):
    bot.add_cog(Timer(bot))
