import serial.tools.list_ports
from gsmmodem2.gsmmodem.modem import GsmModem
import json
import yaml
import logging as logger
from collections import defaultdict
from telegram import Update, Bot
from telegram.ext import Updater, CommandHandler, CallbackContext
import shlex
from functools import wraps
import time
import multiprocessing

mailboxes = json.loads(open("bot_mailbox_tg.json","r",encoding="utf8").read())
classifier_settings = json.loads(open("bot_mailboxes.json","r",encoding="utf8").read())
TG_Bot_Key = json.loads(open("bot_config.json",encoding="utf8").read())["TG_Bot_Key"]
activedevices = {}

def mailbox_classifier(smsSender,smsText,phoneDict,kwordDict,defaultMailbox,mainMailbox):
    if smsSender == None or smsText == None:
        return mainMailbox
    if smsSender in phoneDict.keys():
        return phoneDict[smsSender]
    for keyword,mailbox in reversed(kwordDict.items()):
        if keyword in smsText:
            return mailbox
    return defaultMailbox

def filter_get_number(number):
    return classifier_settings["phoneDict"][number]

def filter_add_number(number,mailbox):
    if number in classifier_settings["phoneDict"]:
        del classifier_settings["phoneDict"][number] 
    classifier_settings["phoneDict"][number] = mailbox
    open("bot_mailboxes.json","w",encoding="utf8").write(json.dumps(classifier_settings,indent=2,ensure_ascii=False))
    return "OK"

def filter_del_number(number):
    del classifier_settings["phoneDict"][number]
    open("bot_mailboxes.json","w",encoding="utf8").write(json.dumps(classifier_settings,indent=2,ensure_ascii=False))
    return "OK"

def filter_get_kword(keyword):
    return classifier_settings["kwordDict"][keyword]

def filter_add_kword(keyword,mailbox):
    if keyword in classifier_settings["kwordDict"]:
        del classifier_settings["kwordDict"][keyword]
    classifier_settings["kwordDict"][keyword] = mailbox
    open("bot_mailboxes.json","w",encoding="utf8").write(json.dumps(classifier_settings,indent=2,ensure_ascii=False))
    return "OK"

def filter_del_kword(keyword):
    del classifier_settings["kwordDict"][keyword]
    open("bot_mailboxes.json","w",encoding="utf8").write(json.dumps(classifier_settings,indent=2,ensure_ascii=False))
    return "OK"

def filter_get_mailbox(mailbox_in=None,recursive=True):
    if mailbox_in == None and recursive==True:
        ret = {}
        all_mailbox = {}
        all_mailbox[classifier_settings["mainMailbox"]] = None
        all_mailbox[classifier_settings["defaultMailbox"]] = None
        for number,mailbox in classifier_settings["phoneDict"].items():
            all_mailbox[mailbox] = None
        for keyword,mailbox in classifier_settings["kwordDict"].items():
            all_mailbox[mailbox] = None
        for mailbox in all_mailbox.keys():
            ret[mailbox] = filter_get_mailbox(mailbox,recursive=False)
        return ret
    phoneList = []
    kwordList = []
    special = []
    for number,mailbox in reversed(classifier_settings["phoneDict"].items()):
        if mailbox == mailbox_in:
            phoneList += [number]
    for keyword,mailbox in reversed(classifier_settings["kwordDict"].items()):
        if mailbox == mailbox_in:
            kwordList += [keyword]
    if classifier_settings["mainMailbox"] == mailbox_in:
        special += ["mainMailbox"]
    if classifier_settings["defaultMailbox"] == mailbox_in:
        special += ["defaultMailbox"]
    ret = {}
    if special != []:
        ret["special mailbox"]=special
    if phoneList != []:
        ret["number"]=phoneList
    if kwordList != []:
        ret["keyword"]=kwordList
    return ret

tg_boardcast_bot = Bot(TG_Bot_Key)
def broadcast_msg(msg,mailbox,parse_mode=None):
    if mailbox not in mailboxes:
        msg = f'Warning: Mailbox "{mailbox}" are not found. Redirect to mailbox "{classifier_settings["mainMailbox"]}".\n' + msg
        mailbox = classifier_settings["mainMailbox"]
    for chatid in mailboxes[mailbox]:
        try:
            tg_boardcast_bot.send_message(chatid,msg,parse_mode=parse_mode)
        except Exception as e:
            print(e)
    return

def handleSms(modem,sms):
    mailbox = mailbox_classifier(sms.number,sms.text,**classifier_settings)
    msg = f"Incoming SMS\nFrom: {sms.number}\nTo: {modem.port}\nContent:\n" + sms.text
    broadcast_msg(msg,mailbox,parse_mode="Markdown")
    return

def handleSmsStauusReport(modem,report):
    mailbox = mailbox_classifier(report.number,"SMS_status_report",**classifier_settings)
    msg = f"SMS Sending Report:\nFrom: {modem.port}\nTo: {report.number}\n" + yaml.dump({"Status":report.status,"time":report.timeSent,"Result":report.deliveryStatus},allow_unicode=True,sort_keys=False)
    broadcast_msg(msg,mailbox,parse_mode="Markdown")
    return

def handlePhoneCall(modem,call):
    mailbox = mailbox_classifier(call.number,"Inoming_phone_call",**classifier_settings)
    msg = f"Incoming Phone Call\nfrom: {call.number}\nTo: {modem.port}"
    call.hangup()
    broadcast_msg(msg,mailbox,parse_mode="Markdown")
    return

def handleUnhandle(modem,lines):
    mailbox = mailbox_classifier(None,"Unhandled_event",**classifier_settings)
    msg = f"Unhendled Events\nFrom: {modem.port}\n{yaml.dump(lines,allow_unicode=True,sort_keys=False)}"
    broadcast_msg(msg,mailbox,parse_mode="Markdown")
    return

def device_scan():
    devicelist = serial.tools.list_ports.comports()
    devicelist = sorted(devicelist,key=lambda x:[x.serial_number,x.description])
    prev_sn = False
    retstr = ""
    for port in devicelist:
        sn = str(port.serial_number)
        desc = str(port.description)
        dev = str(port.device)
        hwid = str(port.hwid)
        retstr += "" if prev_sn == False else "\n" if prev_sn == sn else "==============================\n"
        prev_sn = sn
        retstr += f"SN:\t{sn}\n"
        retstr += f"desc:\t{desc}\n"
        retstr += f"dev:\t{dev}\n"
        retstr += f"HwID:\t{hwid}\n"
#         retstr += f"Init:\t{initinfo}\n"
    return retstr

def initadd():
    devices = json.loads(open("bot_devices.json").read())
    for k,v in devices.items():
        try:
            device_add(k,buadrate=v["init"]["modem"]["buadrate"],pin=v["init"]["sim"]["pin"],smsTextMode=v["init"]["modem"]["smsTextMode"],force=v["init"]["modem"]["force"],write2file=False)
            device_open(k)
            device_online(k)
        except Exception as e:
            print(type(e).__name__ , str(e))
    return

def device_add(dev,buadrate=115200,pin=None,smsTextMode=False,force=False,write2file=True):
    buadrate=int(buadrate)
    devicelist = serial.tools.list_ports.comports()
    deviceinfo = {port.device:{"dev":port.device,"SN":port.serial_number} for port in devicelist}
    if dev not in deviceinfo and force == False:
        raise FileNotFoundError('device "' + str(dev) + "\" are not in scanned device list: \n" + yaml.dump(list(sorted(deviceinfo.keys())),allow_unicode=True,sort_keys=False))
    modem = GsmModem(dev, buadrate, smsReceivedCallbackFunc=handleSms , incomingCallCallbackFunc=handlePhoneCall, smsStatusReportCallback=handleSmsStauusReport,unhandledNotificationCallbackFunc=handleUnhandle)
    activedevices[dev] = deviceinfo[dev] if dev in deviceinfo else {"dev":dev,"SN":None}
    activedevices[dev]["modem"] = modem
    activedevices[dev]["init"] = {"modem":{"buadrate":buadrate,"force":force,"smsTextMode":smsTextMode},"sim":{"pin":pin}}
    if write2file:
        open("bot_devices.json","w").write(json.dumps(activedevices,default=lambda o: None,ensure_ascii=False,indent=4))
    return "OK"

def device_open(dev):
    modem = activedevices[dev]["modem"]
    modem_info = activedevices[dev]["init"]["modem"]
    modem.smsTextMode = modem_info["smsTextMode"]
    modem.open()
    return "OK"

def device_online(dev):
    modem = activedevices[dev]["modem"]
    sim_info = activedevices[dev]["init"]["sim"]
    modem.initialize(pin=sim_info["pin"])
    return "OK"

def device_offline(dev):
    modem = activedevices[dev]["modem"]
    return modem.airplaneMode()

def device_close(dev):
    modem = activedevices[dev]["modem"]
    modem.close()
    return "OK"

def device_del(dev):
    modem = activedevices[dev]["modem"]
    if modem.alive != False:
        raise OSError("Device busy, close it first.")
    del activedevices[dev]
    open("bot_devices.json","w").write(json.dumps(activedevices,default=lambda o: None,ensure_ascii=False,indent=4))
    return "OK"

def device_status(dev=None):
    if dev == None:
        allresult = {}
        for d in activedevices.keys():
            allresult[d] = device_status(d)
        return allresult
    modem = activedevices[dev]["modem"]
    result = {}
    result["ModemOpen"] = modem.alive
    try:
        result["SimStatus"] = modem.simStatus()
    except Exception as e:
        result["SimStatus"] = type(e).__name__ + ": " + str(e)
    try:
        result["NetworkName"] = modem.networkName
    except Exception as e:
        result["NetworkName"] = type(e).__name__ + ": " + str(e)
    try:
        result["SignalStrength"] = modem.signalStrength
    except Exception as e:
        result["SignalStrength"] = type(e).__name__ + ": " + str(e)
    try:
        result["IMSI"] = modem.imsi
    except Exception as e:
        result["IMSI"] = type(e).__name__ + ": " + str(e)
    try:
        result["IMEI"] = modem.imei
    except Exception as e:
        result["IMEI"] = type(e).__name__ + ": " + str(e)
    try:
        result["SMSC"] = modem.smsc
    except Exception as e:
        result["SMSC"] = type(e).__name__ + ": " + str(e)
    try:
        result["gsmBusy"] = modem.gsmBusy
    except Exception as e:
        result["gsmBusy"] = type(e).__name__ + ": " + str(e)
    return result

def device_read_sms(dev=None,index=None,delete=False):
    if dev == None:
        alldevresult = {}
        for d in activedevices.keys():
            alldevresult[d] = device_read_sms(d,index,delete)
        return alldevresult
    if index==None or index=="all":
        allsmsresult = {}
        activedevices[dev]["modem"].write('AT+CPMS="ME"')
        for s in activedevices[dev]["modem"].listStoredSms(delete=delete):
            allsmsresult[s.index] = {"number":s.number,"time":s.time,"smsc":s.smsc,"content": s.text}
        return allsmsresult
    index = int(index)
    s = activedevices[dev]["modem"].readStoredSms(index)
    if delete==True:
        activedevices[dev]["modem"].deleteStoredSms(index)
    return {"number":s.number,"time":s.time,"smsc":s.smsc,"content": s.text}

def device_send_sms(dev,number,content):
    return activedevices[dev]["modem"].sendSms(number,content)

initadd()

def start_func(update: Update,context :CallbackContext ) -> None:
    update.message.text = "/mailbox s"
    return mailbox_func(update,context)

def tg_reply_error(f):
    def wrap(update,CallbackContext):
        logger.info("User {user} sent {message}".format(user=update.message.from_user.username, message=update.message.text))
        try:
            return f(update,CallbackContext)
        except Exception as e:
            # Add info to error tracking
            logger.error(str(e))
            update.message.reply_text("Failed:\n" + type(e).__name__ +":\t"+ str(e))
    return wrap
    
@tg_reply_error
def mailbox_func(update: Update,context :CallbackContext ) -> None:
    msg_in = update.message.text
    print(update.message.text)
    command = list(filter(None, shlex.split( update.message.text[1:])))[1:]
    command = [""] if len(command) == 0 else command
    chatid = int(update.message.chat.id)
    if command[0] == "subscribe" or command[0] == "s":
        mailbox = classifier_settings["mainMailbox"] if len(command) < 2 else command[1]
        if mailbox not in mailboxes:
            mailboxes[mailbox] = {}
        mailboxes[mailbox][chatid] = update.message.chat.to_dict()
        update.message.reply_text(f'Hi, you are subscribed to mailbox "{mailbox}" successfully. \n\n{yaml.dump(mailboxes[mailbox][chatid],allow_unicode=True,sort_keys=False)}')
        del mailboxes[mailbox][chatid]["id"]
        open("bot_mailbox_tg.json","w",encoding="utf8").write(json.dumps(mailboxes,indent=2,ensure_ascii=False))
        return
    elif command[0] == "list" or command[0] == "l":
        mailbox = None if len(command) < 2 else command[1]
        mailbox_print = "all" if mailbox == None else f'"{mailbox}"'
        update.message.reply_text(f'Client list in {  mailbox_print  } mailbox(es): \n{yaml.dump(dict(mailboxes) if mailbox == None else dict(mailboxes[mailbox]),allow_unicode=True,sort_keys=False)}')
        return
    elif command[0] == "unsubscribe" or command[0] == "us":
        mailbox = classifier_settings["mainMailbox"] if len(command) < 2 else command[1]
        chatid_2del = chatid if len(command) < 3 else int(command[2])
        chatid_2del = int(chatid_2del)
        del mailboxes[mailbox][chatid_2del]
        if len(mailboxes[mailbox]) == 0:
            del mailboxes[mailbox]
        update.message.reply_text(f'User {chatid_2del} deleted from mailbox "{mailbox}"')
        open("bot_mailbox_tg.json","w",encoding="utf8").write(json.dumps(mailboxes,indent=2,ensure_ascii=False))
        return
    update.message.reply_text("""Usage:
 s [mailbox_name]: Subscribe the mailbox.
 l [mailbox_name]: List all subscribed users in the mailboxes.
 us [mailbox_name] [user id]: Delete me or specific user from the mailbox.
Alias:
 subscribe s
 list l
 unsubscribe us
""")
    return

@tg_reply_error
def device_func(update: Update,context :CallbackContext ) -> None:
    msg_in = update.message.text.split("\n",1)[0]
    print(update.message.text)
    command = list(filter(None, shlex.split( msg_in[1:])))[1:]
    command = [""] if len(command) == 0 else command
    params = [] if len(command) <= 1 else command[1:]
    target_dev = None
    if command[0] == "scan" :
        update.message.reply_text(device_scan())
    elif command[0] == "add" or command[0] == "a":
        params_dict = {pi.split("=")[0]:pi.split("=")[1] for pi in params[1:]}
        ret = device_add(params[0],**params_dict)
        update.message.reply_text(ret)
    elif command[0] == "del" or command[0] == "d":
        ret = device_del(params[0])
        update.message.reply_text(ret)
    elif command[0] == "open":
        ret = device_open(params[0])
        update.message.reply_text(ret)
    elif command[0] == "close":
        ret = device_close(params[0])
        update.message.reply_text(ret)
    elif command[0] == "online" or command[0] == "on":
        ret = device_online(params[0])
        update.message.reply_text(ret)
    elif command[0] == "offline" or command[0] == "off" or command[0] == "airplanemode":
        ret = device_offline(params[0])
        update.message.reply_text(ret)
    elif command[0] == "status" or command[0] == "list" or command[0] == "l":
        ret = device_status(*params)
        ret = yaml.dump(ret,allow_unicode=True,sort_keys=False)
        update.message.reply_text(ret)
    elif command[0] == "readsms" or command[0] == "r":
        ret = device_read_sms(*params)
        ret = yaml.dump(ret,allow_unicode=True,sort_keys=False)
        update.message.reply_text(ret)
    elif command[0] == "sendsms" or command[0] == "s":
        content = update.message.text.split("\n",1)[1]
        device_send_sms(params[0], params[1] , content)
        ret = "SMS Sending..."
        update.message.reply_text(ret)
    elif command[0] == "delsms":
        ret = f"Device: {params[0]}\nFollowing SMSs are deleted:\n"
        ret += yaml.dump(device_read_sms(params[0],params[1],delete=True),allow_unicode=True,sort_keys=False)
        update.message.reply_text(ret)
    else:
        update.message.reply_text( """Usage:
/device scan
/device add devport [buadrate=115200] [pin=1234] [smsTextMode=False] [force=False]
/device del devport
/device open devport
/device close devport
/device online devport
/device offline devport
/device status [devport]
/device readsms [devport [index]]
/device delsms devport [index|all]
/device sendsms devport number (newline)
SMS_content_here
Alias:
 a add
 d del
 on online
 off offline airplanemode
 status list l
 r readsms
 s sendsms
""" )
    return

@tg_reply_error
def filter_func(update: Update,context :CallbackContext ) -> None:
    msg_in = update.message.text
    print(update.message.text)
    command = list(filter(None, shlex.split( msg_in[1:])))[1:]
    command = [""] if len(command) == 0 else command
    params = [] if len(command) <= 1 else command[1:]
    target_dev = None
    if command[0] == "get" or command[0] == "g":
        if params[0] == "number" or params[0] == "n":
            update.message.reply_text( filter_get_number(params[1]) )
        elif params[0] == "kword" or params[0] == "k" or params[0] == "keyword":
            update.message.reply_text( filter_get_kword(params[1]) )
        elif params[0] == "mailbox" or params[0] == "m":
            update.message.reply_text( yaml.dump(filter_get_mailbox(*params[1:]),allow_unicode=True,sort_keys=False)  )
        else:
            update.message.reply_text( "Usage: /filter get [n|k|m|number|kword|mailbox] [target]" )
    elif command[0] == "set" or command[0] == "s":
        if params[0] == "number" or params[0] == "n":
            update.message.reply_text( filter_add_number(params[1],params[2]) )
        elif params[0] == "kword" or params[0] == "k" or params[0] == "keyword":
            update.message.reply_text( filter_add_kword(params[1],params[2]) )
        else:
            update.message.reply_text( "Usage: /filter set [n|k|number|kword] target mailbox" )
    elif command[0] == "del" or command[0] == "d":
        if params[0] == "number" or params[0] == "n":
            update.message.reply_text( filter_del_number(params[1]) )
        elif params[0] == "kword" or params[0] == "k" or params[0] == "keyword":
            update.message.reply_text( filter_del_kword(params[1]) )
        else:
            update.message.reply_text( "Usage: /filter del [n|k|number|kword] target" )
    else:
        update.message.reply_text( """Usage:
/filter get [number|kword|mailbox] [target]
/filter set [number|kword] target mailbox
/filter del [number|kword] target
Alias:
 g get
 s set
 d del
 n number
 k kword keyword
 m mailbox
""" )
    return

@tg_reply_error
def help_func(update: Update,context :CallbackContext ) -> None:
    update.message.reply_text( """Usage:
Use following command to get more info
/mailbox
/m
/device
/d
/filter
/f
""" )
    return

updater = Updater(TG_Bot_Key)
updater.dispatcher.add_handler(CommandHandler('help', help_func))
updater.dispatcher.add_handler(CommandHandler('mailbox', mailbox_func))
updater.dispatcher.add_handler(CommandHandler('m', mailbox_func))
updater.dispatcher.add_handler(CommandHandler('start', start_func))
updater.dispatcher.add_handler(CommandHandler('device', device_func))
updater.dispatcher.add_handler(CommandHandler('d', device_func))
updater.dispatcher.add_handler(CommandHandler('filter', filter_func))
updater.dispatcher.add_handler(CommandHandler('f', filter_func))
updater.start_polling()
updater.idle()