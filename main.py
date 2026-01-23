import json
import xmltodict
import subprocess
import shutil

from wfp.FilePackager import *

bank_dict = {}


# redefine because of there is a print statement in the original function
def fnv_hash_64(data: str):
    hash_num = 14695981039346656037
    data = data.lower().encode()
    for i in data:
        hash_num = ((hash_num * 1099511628211) & 0xffffffffffffffff) ^ i
    return hash_num


def addJsonString(json_data, results=[]):
    if isinstance(json_data, dict):
        for key in json_data:
            if key not in results:
                results.append(key)
            if isinstance(json_data[key], dict) or isinstance(json_data[key], list):
                addJsonString(json_data[key], results)
            elif isinstance(json_data[key], str):
                if json_data[key] not in results:
                    results.append(json_data[key])
    elif isinstance(json_data, list):
        for item in json_data:
            if isinstance(item, dict) or isinstance(item, list):
                addJsonString(item, results)
            elif isinstance(item, str):
                if item not in results:
                    results.append(item)

def outputWwnames(fuzzy=True, guess=True):
    result = ""

    if not fuzzy:
        result += "#@no-fuzzy\n"

    result += "#@repeats-update-caps\n"

    with open("asset_names.txt", "r", encoding="utf-8") as f:
        result += f.read()

    with open("manual_names.txt", "r", encoding="utf-8") as f:
        result += f.read()

    with open("output/unpack/wwnames.txt", "w", encoding="utf-8") as f:
        f.write(result)


def elegantWrite(f, file_data):
    f.write(file_data[0][0])
    if len(file_data) > 1:
        print("[Mian] file name hash collides! Keep the first one.")

def addAllPckFiles(package, directory):
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.pck'):
                file_path = os.path.join(root, file)
                package.addfile(open(file_path, 'rb'))
                # print(f"[Main] added {file} to the package!")


def unpackWwiseBanks(path = "input"):
    package = Package()

    if not os.path.exists("output/unpack"):
        os.makedirs("output/unpack")
    if not os.path.exists(path):
        print("[Main] missing `input` folder!")

    addAllPckFiles(package, path)
    print('支持语言：' + str(package.LANGUAGE_DEF))

    for i in ["SFX", "Chinese", "English", "Japanese", "Korean"]:
        if not os.path.exists(f"output/unpack/{i}"):
            os.makedirs(f"output/unpack/{i}")
        if i.upper() in package.LANGUAGE_DEF:
            langcode = package.LANGUAGE_DEF[i.upper()]
        else:
            continue
        if len(package.map[0]) > 0 and langcode in package.map[0]:
            for j in package.map[0][langcode]:
                file_data = package.get_file_data_by_hash(j, langcode, 0)
                with open(f'output/unpack/{i}/{j}.bnk', 'wb') as f:
                    elegantWrite(f, file_data)
        if len(package.map[1]) > 0 and langcode in package.map[1]:
            for j in package.map[1][langcode]:
                file_data = package.get_file_data_by_hash(j, langcode, 1)
                with open(f'output/unpack/{i}/{j}.wem', 'wb') as f:
                    elegantWrite(f, file_data)
        if len(package.map[2]) > 0 and langcode in package.map[2]:
            for j in package.map[2][langcode]:
                file_data = package.get_file_data_by_hash(j, langcode, 2)
                if not os.path.exists(f"output/unpack/{i}/externals"):
                    os.makedirs(f"output/unpack/{i}/externals")
                with open(f'output/unpack/{i}/externals/{j}.wem', 'wb') as f:
                    elegantWrite(f, file_data)


def extractBankWem():
    for i in ["SFX", "Chinese", "English", "Japanese", "Korean"]:
        result = subprocess.run(['./quickbms', '-F', '*.bnk', '-k', './wwiser_utils/scripts/wwise_bnk_extractor.bms', f'./output/unpack/{i}', f'./output/unpack/{i}'],
                            capture_output=True, text=True)
        print(result.stdout)

def generateBankData():
    result = subprocess.run(['python', 'wwiser.pyz', '-d', 'xml', '-dn', './output/unpack/banks', './output/unpack/**/*.bnk'],
                            capture_output=True, text=True)
    print(result.stdout)


def loadBankXml(use_old=True):
    global bank_dict
    if use_old and os.path.exists("output/unpack/banks_temp.json"):
        with open("output/unpack/banks_temp.json", 'r') as f:
            bank_dict_old = json.load(f)
            # if bank_dict_old["hash"] == fnv_hash_64(xml_string):
            print("[Main] Bank data loaded from cache. If you want to reload, delete the `banks_temp.json` file.")
            bank_dict = bank_dict_old
            return
    with open("output/unpack/banks.xml", 'r', encoding='utf-8') as f:
        xml_string = f.read()
    data_dict = xmltodict.parse("<base>" + xml_string + "</base>")
    hash_map = {}
    for i in ["SFX", "Chinese", "English", "Japanese", "Korean"]:
        hash_map[str(fnv_hash_32(i))] = i
    for bank in data_dict["base"]["root"]:
        bank_cont = parseXmlNode(bank)
        lang = bank_cont["BankHeader"]["AkBankHeader"]["dwLanguageID"]["@value"]
        if hash_map[lang] not in bank_dict:
            bank_dict[hash_map[lang]] = {}
        bank_dict[hash_map[lang]][bank["@filename"]] = bank_cont

    with open("output/unpack/banks_temp.json", 'w') as f:
        # bank_dict["hash"] = fnv_hash_64(xml_string)
        json.dump(bank_dict, f, indent=4)


def parseXmlNode(node):
    result = node
    parseXmlObj("field", node, result)
    parseXmlObj("object", node, result)
    parseXmlLst(node, result)
    return result


def parseXmlObj(obj_name, obj, result):
    if obj_name in obj:
        if isinstance(obj[obj_name], list):
            for item in obj[obj_name]:
                if item["@name"] not in result:
                    result[item["@name"]] = parseXmlNode(item)
                else:
                    if not isinstance(result[item["@name"]], list):
                        foo = result[item["@name"]]
                        result[item["@name"]] = []
                        result[item["@name"]].append(foo)
                    result[item["@name"]].append(parseXmlNode(item))
        elif isinstance(obj[obj_name], dict):
            result[obj[obj_name]["@name"]] = parseXmlNode(obj[obj_name])
        del result[obj_name]


def parseXmlLst(lst, result):
    if "list" in lst:
        lst = lst["list"]
        if isinstance(lst, list):
            for item in lst:
                result[item["@name"]] = []
                appendXmlLstElement("field", item, result[item["@name"]])
                appendXmlLstElement("object", item, result[item["@name"]])
                appendXmlLstElement("list", item, result[item["@name"]])
        else:
            result[lst["@name"]] = []
            appendXmlLstElement("field", lst, result[lst["@name"]])
            appendXmlLstElement("object", lst, result[lst["@name"]])
            appendXmlLstElement("list", lst, result[lst["@name"]])
        del result["list"]


def appendXmlLstElement(obj_name, obj, lst):
    if obj_name in obj:
        if isinstance(obj[obj_name], list):
            for item in obj[obj_name]:
                lst.append(parseXmlNode(item))
        elif isinstance(obj[obj_name], dict):
            lst.append(parseXmlNode(obj[obj_name]))
        del obj[obj_name]


skip_num = 0
completed_files = []


def elegantRename(hash_path, voice_path, ext="wem", log_area="External", gentle=False):
    old_file_name = f"output/unpack/{hash_path}.{ext}"
    new_file_name = f"output/rename/{voice_path}.{ext}"
    if os.path.exists(new_file_name):
        os.remove(new_file_name)
    global completed_files
    if os.path.exists(old_file_name):
        shutil.copy2(old_file_name, new_file_name)
        if old_file_name not in completed_files:
            completed_files.append(old_file_name)
    else:
        if not gentle:
            print(f"[{log_area}] {old_file_name} -> {new_file_name} not found!")
        global skip_num
        skip_num += 1


def deleteCompletedFiles():
    global completed_files
    with open("output/unpack/finished.txt", "w", encoding="utf-8") as f:
        for file in completed_files:
            f.write(file + "\n")
    for file in completed_files:
        os.remove(file)
    completed_files = []

    for i in ["Chinese", "English", "Japanese", "Korean", "SFX"]:
        if not os.path.exists(f"output/rename/unclassified/{i}"):
            os.makedirs(f"output/rename/unclassified/{i}")
        if os.path.exists(f"output/unpack/{i}"):
            if not os.path.exists(f"output/rename/{i}"):
                os.makedirs(f"output/rename/{i}")
            for root, dirs, files in os.walk(f"output/unpack/{i}"):
                for file in files:
                    if file.endswith('.wem'):
                        shutil.copy2(os.path.join(root, file), f"output/rename/unclassified/{i}/{file}")


def renameExtrenalWems():
    if not os.path.exists(f"output/rename"):
        os.makedirs(f"output/rename")

    for i in ["Chinese", "English", "Japanese", "Korean"]:
        if not os.path.exists(f"output/rename/{i}/Voice"):
            os.makedirs(f"output/rename/{i}/Voice")
    if not os.path.exists(f"output/rename/SFX"):
        os.makedirs(f"output/rename/SFX")

    global skip_num
    print(f"[External] skipped {skip_num} files because of unfound hash.")
    skip_num = 0


def renameEventWems(use_index=True):
    def getLoadedItems(bank):
        hirc = bank.get("HircChunk", {})
        loaded_items = hirc.get("listLoadedItem", [])
        loaded_items_map = {}
        for item in loaded_items:
            loaded_items_map[item.get("ulID", item.get("ulStateID", ""))["@value"]] = item
        return loaded_items_map

    def findAudioNode(nodes, audioNodeIdToName, path = ""):
        for node in nodes:
            if "audioNodeId" in node:
                audioNodeIdToName[node["audioNodeId"]["@value"]] = path + node["key"].get("@hashname", node["key"]["@value"])
            elif "pNodes" in node:
                findAudioNode(node["pNodes"], audioNodeIdToName, path + node["key"].get("@hashname", node["key"]["@value"]) + "/")

    def findSwitchNode(nodes, switchNodeIdToName):
        for node in nodes:
            if int(node["ulNumItems"]["@value"]) > 0:
                if int(node["ulNumItems"]["@value"]) == 1:
                    switchNodeIdToName[node["NodeList"]["NodeID"]["@value"]] = node["ulSwitchID"].get("@hashname",
                                                                                                    node["ulSwitchID"][
                                                                                                        "@value"])
                else:
                    for item in node["NodeList"]["NodeID"]:
                        switchNodeIdToName[item["@value"]] = node["ulSwitchID"].get("@hashname",
                                                                                   node["ulSwitchID"]["@value"])

    def getChilds(node, result):
        if "ulNumChilds" in node:
            if int(node["ulNumChilds"]["@value"]) > 0:
                if int(node["ulNumChilds"]["@value"]) == 1:
                    result.append(node["ulChildID"]["@value"])
                else:
                    for child in node["ulChildID"]:
                        result.append(child["@value"])
        return result

    def findMusicSound(sound_id, musicSegments, musicTracks, musicRanSeqCntrs, musicSwitchCntrs, path, result):
        if sound_id in musicSwitchCntrs:
            for child in musicSwitchCntrs[sound_id]:
                subpath = path
                subpath += f"/{musicSwitchCntrs[sound_id][child]}"
                findMusicSound(child, musicSegments, musicTracks, musicRanSeqCntrs, musicSwitchCntrs, subpath, result)
        if sound_id in musicRanSeqCntrs:
            childs = []
            getChilds(musicRanSeqCntrs[sound_id], childs)
            for child in childs:
                findMusicSound(child, musicSegments, musicTracks, musicRanSeqCntrs, musicSwitchCntrs, path, result)
        if sound_id in musicSegments:
            childs = []
            getChilds(musicSegments[sound_id], childs)
            for child in childs:
                findMusicSound(child, musicSegments, musicTracks, musicRanSeqCntrs, musicSwitchCntrs, path, result)
        if sound_id in musicTracks:
            for source in musicTracks[sound_id]:
                subpath = path
                subpath += f"/{source["AkMediaInformation"]["sourceID"]["@value"]}"
                result[source["AkMediaInformation"]["sourceID"]["@value"]] = subpath

    def findSound(sound_id, loaded_items, normal_sound_path, lang, path, results):
        def renameSource(source, index, source_index):
            source_sound_path = normal_sound_path
            if source["AkMediaInformation"]["uSourceBits"]["bIsLanguageSpecific"]["@value"] == "0":
                source_sound_path = normal_sound_path.replace(f"{lang}", "sfx")
            name = source["AkMediaInformation"]["sourceID"]["@value"]
            file2rename = f"{source_sound_path[14:]}/{name}"
            if use_index:
                index_string = f"{index}{'~' if source_index else ''}{source_index}~"
            else:
                index_string = ""
            file_destination = f"{normal_sound_path[14:]}/{path}/{index_string}{name}"
            if not os.path.exists(f"output/rename/{normal_sound_path[14:]}/{path}"):
                os.makedirs(f"output/rename/{normal_sound_path[14:]}/{path}")
            results.append((file2rename, file_destination))

        if sound_id in loaded_items:
            name = loaded_items[sound_id]["@name"]

            if name == "CAkSwitchCntr":
                node_id2name = {}
                childs = []
                getChilds(loaded_items[sound_id]["SwitchCntrInitialValues"]["Children"], childs)
                findSwitchNode(loaded_items[sound_id]["SwitchCntrInitialValues"]["SwitchList"], node_id2name)
                for child in node_id2name:
                    subpath = path
                    subpath += f"/{node_id2name[child]}"
                    findSound(child, loaded_items, normal_sound_path, lang, subpath, results)
                    if child in childs:
                        childs.remove(child)
                for child in childs:
                    findSound(child, loaded_items, normal_sound_path, lang, path + f"/unswitched-{child}", results)

            if name == "CAkRanSeqCntr":
                childs = []
                getChilds(loaded_items[sound_id]["RanSeqCntrInitialValues"]["Children"], childs)
                for child in childs:
                    findSound(child, loaded_items, normal_sound_path, lang, path, results)

            if name == "CAkLayerCntr":
                childs = []
                getChilds(loaded_items[sound_id]["LayerCntrInitialValues"]["Children"], childs)
                for child in childs:
                    findSound(child, loaded_items, normal_sound_path, lang, path, results)

            if name == "CAkSound":
                source = loaded_items[sound_id]["SoundInitialValues"]["AkBankSourceData"]
                renameSource(source, loaded_items[sound_id]["@index"], "")

            if name == "CAkMusicSwitchCntr":
                node_id2name = {}
                childs = []
                getChilds(
                    loaded_items[sound_id]["MusicSwitchCntrInitialValues"]["MusicTransNodeParams"]["MusicNodeParams"][
                        "Children"], childs)
                findAudioNode(loaded_items[sound_id]["MusicSwitchCntrInitialValues"]["AkDecisionTree"]["pNodes"],
                              node_id2name)
                for child in node_id2name:
                    subpath = path
                    subpath += f"/{node_id2name[child]}"
                    findSound(child, loaded_items, normal_sound_path, lang, subpath, results)
                    if child in childs:
                        childs.remove(child)
                for child in childs:
                    findSound(child, loaded_items, normal_sound_path, lang, path + f"/unswitched-{child}", results)

            if name == "CAkMusicRanSeqCntr":
                childs = []
                getChilds(
                    loaded_items[sound_id]["MusicRanSeqCntrInitialValues"]["MusicTransNodeParams"]["MusicNodeParams"][
                        "Children"], childs)
                for child in childs:
                    findSound(child, loaded_items, normal_sound_path, lang, path, results)

            if name == "CAkMusicSegment":
                childs = []
                getChilds(loaded_items[sound_id]["MusicSegmentInitialValues"]["MusicNodeParams"]["Children"], childs)
                for child in childs:
                    findSound(child, loaded_items, normal_sound_path, lang, path, results)

            if name == "CAkMusicTrack":
                for source in loaded_items[sound_id]["MusicTrackInitialValues"]["pSource"]:
                    renameSource(source, loaded_items[sound_id]["@index"], source["@index"])

    if not os.path.exists(f"output/rename"):
        os.makedirs(f"output/rename")

    for lang in bank_dict:
        if lang == "hash":
            continue
        for bank_name in bank_dict[lang]:
            print(f"[Event] {lang}: {bank_name}")
            bank = bank_dict[lang][bank_name]

            loaded_items_map = getLoadedItems(bank)

            processed = False
            global completed_files

            for item_id in loaded_items_map:
                item = loaded_items_map[item_id]
                if item["@name"] == "CAkEvent":
                    # print(f"[Event] processing event {item['ulID'].get('@hashname', item['ulID']['@value'])}...")
                    event_id = item["ulID"]["@value"]
                    event_name = item["ulID"].get("@hashname", event_id)
                    for action in item["EventInitialValues"]["actions"]:
                        action_item = loaded_items_map[action["ulActionID"]["@value"]]
                        if action_item["@name"] == "CAkActionPlay":
                            params = action_item["ActionInitialValues"]["PlayActionParams"]
                            id_ext = action_item["ActionInitialValues"]["idExt"]["@value"]
                            for sound_lang in (["SFX", lang] if lang != "SFX" else ["SFX", "Chinese", "English", "Japanese", "Korean"]):
                                if sound_lang in bank_dict and (params["bankID"]["@value"] + ".bnk" in bank_dict[sound_lang] or params["bankID"].get("@hashname", "") + ".bnk" in bank_dict[sound_lang] or params["bankID"].get("@guidname", "") + ".bnk" in bank_dict[sound_lang]):
                                    sound_bank = bank_dict[sound_lang].get(params["bankID"]["@value"] + ".bnk", bank_dict[sound_lang].get(params["bankID"].get("@hashname", "") + ".bnk", bank_dict[sound_lang].get(params["bankID"].get("@guidname", "") + ".bnk", None)))
                                    if sound_bank is None:
                                        # print(f"[Event] ERR: {sound_lang}: {sound_bank} cannot be found!")
                                        continue
                                    sound_bank_loaded_items_map = getLoadedItems(sound_bank)

                                    sound_processed = False

                                    normal_sound_path = sound_bank["@path"].replace("\\", "/").replace("./", "")

                                    if id_ext in sound_bank_loaded_items_map:
                                        rename_list = []
                                        findSound(id_ext, sound_bank_loaded_items_map, normal_sound_path, lang, event_name, rename_list)
                                        for pair in rename_list:
                                            elegantRename(pair[0], pair[1], "wem", "Event")
                                        sound_processed = True

                                    if sound_processed and f"{normal_sound_path}/{sound_bank["@filename"]}" not in completed_files:
                                        completed_files.append(f"{normal_sound_path}/{sound_bank["@filename"]}")
                                else:
                                    # print(f"[Event] ERR: {sound_lang}: {params['bankID']['@value']}.bnk cannot be found!")
                                    pass

                    processed = True

            normal_path = bank["@path"].replace("\\", "/").replace("./", "")
            if processed and f"{normal_path}/{bank["@filename"]}" not in completed_files:
                completed_files.append(f"{normal_path}/{bank["@filename"]}")

    global skip_num
    print(f"[Event] skipped {skip_num} files because of unfound hash.")
    skip_num = 0

def decodeWems():
    for root, dirs, files in os.walk("output/rename"):
        for file in files:
            if file.endswith(".wem"):
                path = root.replace("\\", "/") + "/" + file
                short_path = path.replace("output/rename/", "").replace("wem", "wav")
                if not os.path.exists(f"output/decode/{short_path}"):
                    os.makedirs(os.path.dirname(f"output/decode/{short_path}"), exist_ok=True)
                subprocess.run(
                    ["./vgmstream/vgmstream-cli", path, "-o", f"output/decode/{short_path}"])

from convert_ogg import WwiseOpusConverter

def decodeWemsToOgg():
    for root, dirs, files in os.walk("output/rename"):
        for file in files:
            if file.endswith(".wem"):
                path = root.replace("\\", "/") + "/" + file
                short_path = path.replace("output/rename/", "").replace("wem", "ogg")
                if not os.path.exists(f"output/decode_unrevorbed/{short_path}"):
                    os.makedirs(os.path.dirname(f"output/decode_unrevorbed/{short_path}"), exist_ok=True)
                if not os.path.exists(f"output/decode/{short_path}"):
                    os.makedirs(os.path.dirname(f"output/decode/{short_path}"), exist_ok=True)
                converter = WwiseOpusConverter(path)
                try:
                    converter.convert(f"output/decode/{short_path}")
                    print(f"Successfully converted {path} to {f"output/decode/{short_path}"}")
                except Exception as e:
                    print(f"Error converting: {e}, trying ww2ogg")
                    subprocess.run(
                        ["./ww2ogg", path, "-o", f"output/decode_unrevorbed/{short_path}", "--pcb", "packed_codebooks_aoTuV_603.bin"])
                    subprocess.run(
                        ["./revorb", f"output/decode_unrevorbed/{short_path}", f"output/decode/{short_path}"])




if __name__ == '__main__':
    print("[Main] Start!")
    print("[Main] Start unpacking Wwise banks...")
    unpackWwiseBanks(r"E:\BeyondTools\BeyondTools.VFS\bin\Release\net9.0\output\Data\Audio")
    print("[Main] Start extracting bank wems...")
    extractBankWem()
    # if you just want to unpack but not rename, comment all lines below
    print("[Main] Start outputting wwnames...")
    outputWwnames(False, False)
    print("[Main] Start generating bank data...")
    generateBankData()
    print("[Main] Start loading bank xml...")
    loadBankXml(False)
    print("[Main] Start renaming external wems...")
    renameExtrenalWems()
    print("[Main] Start renaming event wems...")
    renameEventWems(False)
    print("[Main] Start deleting completed files...")
    # this program will delete the files in the `output/unpack` folder which are successfully renamed.
    # if you want to keep them, comment the line below.
    deleteCompletedFiles()
    print("[Main] Start decoding wems...")
    # decodeWems()
    decodeWemsToOgg()
    print("[Main] Done!")