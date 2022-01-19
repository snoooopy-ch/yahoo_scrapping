# https://login.yahoo.co.jp/config/login
# slack token取得
# https://api.slack.com/custom-integrations/legacy-tokens
# slack web hook取得
# https://matz.slack.com/apps/new/A0F7XDUAZ-incoming-webhooks

import time
import sys
from datetime import datetime, date, timedelta
import re
import csv
import json
#import pandas as pd

from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common import exceptions as selExceptions
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

import requests
import lxml.html
import os
import subprocess
import traceback
from orator import DatabaseManager

import logging

LOG_LEVEL = logging.INFO

logger = logging.getLogger("")
formatter = logging.Formatter(
    fmt="[%(asctime)s] %(levelname)s [%(threadName)s] [%(name)s/%(funcName)s() at line %(lineno)d]: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

logger.setLevel(LOG_LEVEL)

BASE_URL = 'https://www.yahoo.co.jp'
IMG_FOLDER = 'img/'
WAIT = 10
DBG = 0
download_path = './download'

# DB setting
DB_HOST = '127.0.0.1'
DB_NAME = 'yahoo_ad'
DB_USER = 'root'
DB_PASS = 'WU4vx&j3*y7Avic&'

# slack setting
SLACK_TEST = 0
SLACK_WEBHOOK = ""
SLACK_USERNAME = ''
SLACK_CHANNEL = "#general"


def db_conn():
    try:
        config = {
            'mysql': {
                'driver': 'mysql',
                'host': DB_HOST,
                'database': DB_NAME,
                'user': DB_USER,
                'password': DB_PASS,
                'prefix': '',
                'log_queries': False
            }
        }
        db = DatabaseManager(config)

    except Exception as e:
        #slack_post("DB connect error:{}".format(e))
        print("exception: {}".format(e))

    return db


def slack_post(message):
    payload = {
        "text": message,
        "username": SLACK_USERNAME,
        "channel": SLACK_CHANNEL,
    }
    r = requests.post(SLACK_WEBHOOK, data=json.dumps(payload))
    return r


def screenShotFull(driver, filename, timeout=30):
    """フルページ スクリーンショット"""

    # url取得
    url = driver.current_url

    # ページサイズ取得
    w = driver.execute_script("return document.body.scrollWidth;")
    h = driver.execute_script("return document.body.scrollHeight;")

    if sys.platform.startswith('linux'):
        binary_location = '/usr/bin/google-chrome'
    else:
        binary_location = "/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome"

    cmd = '{} --headless --hide-scrollbars --incognito --no-sandbox --screenshot={} --window-size={},{} "{}"'.format(binary_location, filename, w, h, url)

    # print(cmd)

    # コマンド実行
    subprocess.Popen(cmd, shell=True,
                     stdout=subprocess.PIPE,
                     stderr=subprocess.STDOUT)


def compact(locals, *keys):
    return dict((k, locals[k]) for k in keys)


def init_selenium2():
    browser = webdriver.Remote(
        command_executor='http://selenium-hub:4444/wd/hub',
        desired_capabilities=DesiredCapabilities.CHROME)
    return browser

def init_selenium():
    chromeOptions = webdriver.ChromeOptions()
    chromeOptions.add_argument("--headless")
    chromeOptions.add_argument("--remote-debugging-port=9222")
    chromeOptions.add_argument('--no-sandbox')
    chromeOptions.add_argument("lang=ja_JP") 
    chromeOptions.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/61.0.3163.100 Safari/537.36")
    driver = webdriver.Chrome('/usr/bin/chromedriver',chrome_options=chromeOptions)  

    return driver


def download_img(url, file_name):
    r = requests.get(url, stream=True)
    if r.status_code == 200:
        with open(file_name, 'wb') as f:
            f.write(r.content)


if __name__ == '__main__':
    start = time.time()

    db = db_conn()
    csv_datas = []

    if SLACK_TEST:
        message = "test"
        res = slack_post(message)
        sys.exit()

    try:
        driver = init_selenium() 
        for user in db.table('users').get():

            acc_category = ('男性' if user['is_male']==1 else '女性') + ' ' + user['age']

            driver.get('https://login.yahoo.co.jp/config/login?.src=www&.done=https://www.yahoo.co.jp')

            # login page loading...
            time.sleep(1)
            try:
                input_id = driver.find_element_by_xpath('//input[@name="login"]')
                input_id.send_keys(user['email'])
                driver.find_element_by_xpath("//button[@id='btnNext']").click()
                
                time.sleep(2)
            except Exception:
                pass

            input_pw = driver.find_element_by_xpath('//input[@id="passwd"]')
            input_pw.send_keys(user['password'])

            driver.find_element_by_xpath("//button[@id='btnSubmit']").click()

            # login wait
            time.sleep(2)

            body = driver.page_source
            dom = lxml.html.fromstring(body)
            # screenShotFull(driver, filename='./screenshot0.png')
            # driver.save_screenshot('/root/screenshot0.png')

            datas = []
            urls = []
            texts = []
            banner_urls = []

            print(body)

            for i, ad in enumerate(dom.xpath('//div[contains(@id,"STREAM")]')):
                url = ad.xpath('./div/a/@href')[0]
                text = ad.xpath('./div/div/dl')[0].text_content().strip()
                # banner_urlはローカルに保存
                banner_url = ad.xpath('./div/div[2]/span/img/@src')[0]

                data = {'ad_row': i+1, 'ad_url': url, 'ad_text': re.sub(r" +", " ", text), 'ad_banner_url': banner_url}
                datas.append(data)

            # 一度広告URLを取得してから、キャプチャを取る
            for data in datas:
                driver.get(data['ad_url'])

                insert_data = {'account_category': acc_category, 'ad_row': data['ad_row'], 'ad_url': data['ad_url'], 'ad_text': data['ad_text']}
                insert_data['created_at'] = datetime.strftime(datetime.today(), '%Y-%m-%d %H:%M:%S')
                insert_data['updated_at'] = datetime.strftime(datetime.today(), '%Y-%m-%d %H:%M:%S')

                try:
                    ads_id = db.table('ads').insert_get_id(insert_data)
                except Exception as e:
                    print("DB INSERT Exception : {}".format(e))

                # todo : DBの広告IDを振って、そのIDを利用してファイル保存を行う
                img_path = "img/{}/".format(ads_id)
                # window sizeでのキャプチャ
                # driver.save_screenshot(img_path + 'screenshot_winsize.png')

                ad_screen_shot_path = img_path + 'screenshot.png'
                ad_banner_path = img_path + 'banner.jpg'
                os.makedirs(img_path, exist_ok=True)
                screenShotFull(driver, filename=ad_screen_shot_path)
                download_img(data['ad_banner_url'], ad_banner_path)
                # driver.back()

                update_data = {'ad_screen_shot_path': ad_screen_shot_path, 'ad_banner_path': ad_banner_path}

                csv_datas.append({'アカウントカテゴリ': acc_category, 'ランク': data['ad_row'], '広告URL': data['ad_url'], '広告テキスト': data['ad_text'], '広告スクリーンショット': ad_screen_shot_path, 'バナー': ad_banner_path, "実行日時": datetime.strftime(datetime.today(), '%Y-%m-%d %H:%M:%S')})

                try:
                    ads_id = db.table('ads').where('id', ads_id).update(update_data)
                except Exception as e:
                    print("DB UPDATE Exception : {}".format(e))

            # print(datas)
            # time.sleep(1)

        raise ValueError("exit")

    except KeyboardInterrupt:
        pass
    except Exception as e:
        # slack_post("error:{}".format(e))
        logger.warning("Exception : {} : {}".format(e, traceback.format_exc()))
        print("exception:{}".format(e))
    finally:
        driver.quit()

    if len(csv_datas)>0:
        column_order = ["アカウントカテゴリ", "ランク", "広告URL", "広告テキスト", "広告スクリーンショット", "バナー", "実行日時"]
        df = pd.DataFrame(csv_datas)
        df.to_csv(datetime.now().strftime('%Y%m%d_%H%M%S') + '.tsv', sep='\t', index=False, quoting=csv.QUOTE_ALL,
                  columns=column_order)
        # df.to_csv(datetime.now().strftime('%Y%m%d_%H%M%S') + '.csv', sep=',', index=False, quoting=csv.QUOTE_ALL,
        #           columns=column_order, encoding='utf_8_sig')

    print("finished! elapsed_time:{:.1f}s".format(time.time() - start))
    sys.exit()