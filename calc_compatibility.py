import re
import datetime
import emoji
import sys

def read_txt(filepath):
    with open(filepath, 'r') as f:
        lines = f.readlines()
        lines = [line.strip() for line in lines]
    return lines


def classify_text_type(line):
    date_pat = r'(\d{4})/(\d{2})/(\d{2})(\(.*\))'
    message_pat = r'(\d{2}):(\d{2})\t(.*)\t(.*)'

    is_date = re.search(date_pat, line)
    is_message = re.search(message_pat, line)

    if is_date:
        return {
            'type': 'date', 
            'date': {'year': is_date[1], 'month': is_date[2], 'day': is_date[3]}
        }
    elif is_message:
        return {
            'type': 'message', 
            'time': {'hour': is_message[1], 'minutes': is_message[2]},
            'name': is_message[3],
            'content': is_message[4]
        }
    elif len(line) != 0:
        return {
            'type': 'nl_message', 
            'content': line
        }
    else:
        return None




# 送信時間を計算
def calc_date_time(classified_lines):
    date = {}
    calced_date_time_lines = []
    for i in range(len(classified_lines)):
        line = classified_lines[i]
        if line['type'] == 'date':
            date = line['date']
        elif line['type'] == 'message':
            time = line['time']
            line['time'] = datetime.datetime(
                int(date['year']), 
                int(date['month']), 
                int(date['day']), 
                int(time['hour']), 
                int(time['minutes'])
            )
            calced_date_time_lines.append(line)
        else:
            calced_date_time_lines.append(line)
    return calced_date_time_lines


# 本文結合
def bind_message_by_turn(messages):
    binded_messages = []
    is_start_bind = True
    bind_index = 0
    for i in range(len(messages)):
        message = messages[i]
        message['content'] = [message['content']]
        # 二行目から判定開始
        if i == 0:
            continue
        # 結合しはじめかを判定
        # if is_start_bind:
        #     bind_index = i-1
        if message['type'] == 'nl_message':
            messages[bind_index]['content'].extend(message['content'])
            is_start_bind = False
            if i == len(messages) - 1:
                binded_messages.append(messages[bind_index])
        elif message['name'] == messages[bind_index]['name']:
            # 1時間以上経過で別ターンとして扱う
            if message['time'] - messages[bind_index]['time'] > datetime.timedelta(hours=1):
                binded_messages.append(messages[bind_index])
                is_start_bind = True
                bind_index = i
            else:
                messages[bind_index]['content'].extend(message['content'])
                is_start_bind = False
            if i == len(messages) - 1:
                binded_messages.append(messages[bind_index])
        else:
            binded_messages.append(messages[bind_index])
            is_start_bind = True
            bind_index = i
    return binded_messages


# 会話単位で結合
def bind_turn_by_conversation(turn_list):
    conversation_list = []
    conversation = []
    is_start_conv = True
    for i in range(len(turn_list)):
        turn = turn_list[i]
        if i == 0:
            conversation.append(turn)
            continue
        prev_turn = turn_list[i-1]
        # 1日以上経過で会話終了(TODO: 最後の会話が疑問形の場合は会話を区切らない？)
        if turn['time'] - prev_turn['time'] > datetime.timedelta(days=1):
            conversation_list.append(conversation)
            conversation = [turn]
        else:
            conversation.append(turn)
            if i == len(turn_list) - 1:
                conversation_list.append(conversation)
    return conversation_list


# 会話の継続率
def calc_conversation_continuous(conversation_list, max_score):
    total_score = 0
    for conversation in conversation_list:
        delta = conversation[len(conversation)-1]['time'] - conversation[0]['time']
        persistence = delta / datetime.timedelta(days=10)
        if persistence > 1:
            persistence = 1
        total_score += max_score*persistence
    return total_score / len(conversation_list)


# 返信間隔
def calc_reply_interval(conversation_list, user_name, max_score):
    total_score = 0
    num_valid_pair = 0
    for conversation in conversation_list:
        for i, turn in enumerate(conversation):
            if i == 0 and turn['name'] != user_name:
                continue
            if turn['name'] == user_name:
                start = turn
            else:
                delta = turn['time'] - start['time']
                interval = (datetime.timedelta(hours=6) - delta) / datetime.timedelta(hours=6)
                num_valid_pair += 1
                if interval >= 0:
                    total_score += max_score*interval
    return total_score / num_valid_pair


# 内容判断
def calc_content_quarity(conversation_list, user_name, max_score):
    def is_question(message):
        return '？' in message
    def is_contain_emoji(message):
        for ch in message:
            if ch in emoji.UNICODE_EMOJI:
                return True
        return False
    total_score = 0
    num_target_turn = 0
    for conversation in conversation_list:
        for turn in conversation:
            if turn['name'] != user_name:
                num_target_turn += 1
                for message in turn['content']:
                    if is_question(message) or is_contain_emoji(message):
                        total_score += max_score
                        continue
    return total_score / num_target_turn


def calc_num_duration(conversation_list, max_score):
    def is_call(message):
        call_pat = r'☎ 通話時間\s(\d+:\d+:\d+|\d+:\d+|\d+)'
        return re.search(call_pat, message)

    def calc_call_time(result):
        splited_call_time = result[1].split(':')
        call_time = {}
        if len(splited_call_time) == 3:
            call_time = datetime.timedelta(
                hours=int(splited_call_time[0]), 
                minutes=int(splited_call_time[1]), 
                seconds=int(splited_call_time[2])
            )
        elif len(splited_call_time) == 2:
            call_time = datetime.timedelta(
                hours=0, 
                minutes=int(splited_call_time[0]), 
                seconds=int(splited_call_time[1])
            )
        elif len(splited_call_time) == 1:
            call_time = datetime.timedelta(
                hours=0, 
                minutes=0, 
                seconds=int(splited_call_time[0])
            )
        return call_time
    total_score = 0
    num_call = 0
    for conversation in conversation_list:
        for turn in conversation:
            for message in turn['content']:
                result = is_call(message)
                if result:
                    num_call += 1
                    call_time = calc_call_time(result)
                    call_time_rate = call_time / datetime.timedelta(hours=1)
                    if call_time_rate >= 1:
                        call_time_rate = 1
                    total_score += max_score*call_time_rate
    return total_score / num_call


def main():
    read_file_path = 'path/to/line.txt'
    user_name = 'user_name'
    lines = read_txt(read_file_path)[3:]


    classified_lines = []
    # ラインを日付とメッセージに分類
    for line in lines:
        result = classify_text_type(line) 
        if result is not None:
            classified_lines.append(result)

    # 日付を計算
    calced_datetime_lines = calc_date_time(classified_lines)
    # ターンに結合
    turn_list = bind_message_by_turn(calced_datetime_lines)
    # 会話に結合
    conversation_list = bind_turn_by_conversation(turn_list)


    # 配点
    PERSISTENCE_RATE_MAX_SCORE = 25
    INTERVAL_MAX_SCORE = 25
    CONTENT_MAX_SCORE = 25
    CALL_MAX_SCORE = 25


    # 会話の継続率計算
    score_cc = calc_conversation_continuous(conversation_list, PERSISTENCE_RATE_MAX_SCORE)
    # 会話の間隔
    interval_score = calc_reply_interval(conversation_list, user_name, INTERVAL_MAX_SCORE)
    # 会話の内容
    content_score = calc_content_quarity(conversation_list, user_name, CONTENT_MAX_SCORE)
    # 通話時間
    call_score = calc_num_duration(conversation_list, CALL_MAX_SCORE)

    total_score = score_cc + interval_score + content_score + call_score

    print("*"*36)
    print(f"****\t会話の長さ\t{int(score_cc)} 点\t****")
    print(f"****\t返信間隔\t{int(interval_score)}点\t****")
    print(f"****\t内容の質\t{int(content_score)}点\t****")
    print(f"****\t通話時間\t{int(call_score)}点\t****")
    print("*"*36)
    print(f"****\t総合得点\t{int(total_score)}点\t****")
    print("*"*36)


if __name__ == '__main__':    
    main()
