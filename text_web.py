import uvicorn
if __name__ == '__main__':
    uvicorn.run('text_web:app', host='127.0.0.1', port=33339, log_level="info")
from typing import Optional, Union
from pydantic import BaseModel
from fastapi import FastAPI, File, Form, HTTPException, Response, status
# import faiss
from os import listdir
import numpy as np
from tqdm import tqdm
import cv2
import sqlite3
import json
import math
from paddleocr import PaddleOCR
ocr_ru = PaddleOCR(use_angle_cls=True, lang="ru",show_log = False)
ocr_en = PaddleOCR(use_angle_cls=True, lang="en",show_log = False)

conn = sqlite3.connect('ocr_text_ru_eng.db')



from fonetika.metaphone import RussianMetaphone
METAPHONE_RU=RussianMetaphone()

from abydos import phonetic
METAPHONE_ENG=phonetic.Metaphone()

from transliterate import translit
from rapidfuzz.distance import Levenshtein
import re
# IMAGE_PATH = "./../../../public/images"
# sub_index = faiss.IndexFlat(512, faiss.METRIC_L1)
# index_id_map = faiss.IndexIDMap2(sub_index)

IMG_ID_TXT_ARR={}

def get_all_data_iterator(arraysize=10000):
    cursor = conn.cursor()
    query = '''
        SELECT id, text_arr
        FROM ocr_text
        '''
    cursor.execute(query)
    while True:
        results = cursor.fetchmany(arraysize)
        if not results:
            break
        yield results

def init_index():
    for batch in tqdm(get_all_data_iterator(10000)):
        for el in batch:
            text_arr=json.loads(el[1])
            IMG_ID_TXT_ARR[el[0]]=text_arr
    print(IMG_ID_TXT_ARR["312649"])
    print(f"Data entries in index: {len(IMG_ID_TXT_ARR)}")
    print("Index is ready")

def get_text_by_image_id(id):
    cursor = conn.cursor()
    query = '''
    SELECT text_arr
    FROM ocr_text
    WHERE id = (?)
    '''
    cursor.execute(query, (id,))
    all_rows = cursor.fetchone()
    return all_rows[0]

def create_table():
    cursor = conn.cursor()
    query = '''
	    CREATE TABLE IF NOT EXISTS ocr_text(
	    	id INTEGER NOT NULL UNIQUE PRIMARY KEY, 
	    	text_arr TEXT NOT NULL
	    )
	'''
    cursor.execute(query)
    conn.commit()


def check_if_exists_by_id(id):
    cursor = conn.cursor()
    query = '''SELECT EXISTS(SELECT 1 FROM ocr_text WHERE id=(?))'''
    cursor.execute(query, (id,))
    all_rows = cursor.fetchone()
    return all_rows[0] == 1


def delete_descriptor_by_id(id):
    cursor = conn.cursor()
    query = '''DELETE FROM ocr_text WHERE id=(?)'''
    cursor.execute(query, (id,))
    conn.commit()

def get_all_ids():
    cursor = conn.cursor()
    query = '''SELECT id FROM ocr_text'''
    cursor.execute(query)
    all_rows = cursor.fetchall()
    return list(map(lambda el: el[0], all_rows))

def add_descriptor(id, text_arr):
    cursor = conn.cursor()
    query = '''INSERT INTO ocr_text(id, text_arr) VALUES (?,?)'''
    cursor.execute(query, (id, text_arr))
    conn.commit()


class MyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        else:
            return super(MyEncoder, self).default(obj)

def convert_to_words_arr(text_arr):
    words_arr=[]
    for entry in text_arr:
        word=entry[1][0].lower()
        # words_arr.append(word)
        word = word.strip()
        words_split= word.split()
        words_arr.extend(words_split)
    words_arr.append("".join(words_arr))
    words_arr = [word for word in words_arr if len(word) > 3]
    words_arr=list(set(words_arr))
    return words_arr

# def sync_db():
#     ids_in_db = set(get_all_ids())
#     file_names = listdir(IMAGE_PATH)
#     for file_name in file_names:
#         file_id = int(file_name[:file_name.index('.')])
#         if file_id in ids_in_db:
#             ids_in_db.remove(file_id)
#     for id in ids_in_db:
#         delete_descriptor_by_id(id)  # Fix this
#         print(f"deleting {id}")
#     print("db synced")

def find_similar_by_text(query_text_arr):
    pass

def read_img_file(image_data):
    return np.fromstring(image_data, np.uint8)

def resize_img_to_threshold(img):
    height,width=img.shape
    threshold=2000*1500
    if height*width>threshold:
        k=math.sqrt(height*width/(threshold))
        img=cv2.resize(img, (round(width/k),round(height/k)), interpolation=cv2.INTER_LINEAR)
    return img

def get_ocr_text(image_buffer):
    query_image = cv2.imdecode(read_img_file(image_buffer),cv2.IMREAD_GRAYSCALE)
    query_image = resize_img_to_threshold(query_image)
    query_image = cv2.copyMakeBorder(query_image, 50, 50, 50, 50, cv2.BORDER_CONSTANT, value=[255,255,255])
    # query_image = cv2.fastNlMeansDenoising(query_image, h=7, templateWindowSize=7, searchWindowSize=21)

    result_ru = ocr_ru.ocr(query_image, cls=True)
    result_en = ocr_en.ocr(query_image, cls=True)
    final_words = []
    for txt in result_ru:
        coords_ru=str(txt[0])
        flag1 = False
        for _txt in result_en:
            coords_en=str(_txt[0])
            if coords_ru == coords_en:
                flag1 = True
                if txt[1][1] > _txt[1][1]:
                    final_words.append(txt)
                else:
                    final_words.append(_txt)
                break
        if flag1 == False:
            final_words.append(txt)
    # print(final_words)
    for txt in result_en:
        coords_en=str(txt[0])
        flag1 = False
        for _txt in final_words:
            coords=str(_txt[0])
            if coords_en == coords:
                flag1 = True
                break
        if flag1 == False:
            final_words.append(txt)
    # print(final_words)
    return final_words


def has_cyrillic(text):
    return bool(re.search('[??-????-??]', text))

def cmp_string(algo,word1,word2):
    if algo == "leven":
        return 100*Levenshtein.normalized_similarity(word1,word2,weights=(2,2,1))
    # if algo == "jaro_winkler":
    #     return string_metric.jaro_winkler_similarity(word1, word2)

def text_find_similar(text_arr,k, distance_threshold):
    words_arr = convert_to_words_arr(text_arr)
    print(words_arr)
    similar = {}
    for key,value in tqdm(IMG_ID_TXT_ARR.items()): #key == image_id
        for target_word in words_arr:
            target_word_is_cyrillic=has_cyrillic(target_word)
            db_words=convert_to_words_arr(value)
            relevant=[]
            for db_word in db_words:
                metaphone_en_score=0
                metaphone_ru_score=0
                leven_score=0
                if has_cyrillic(db_word) == target_word_is_cyrillic: #both target and db words are cyrillic or both are not cyrillic
                    leven_score=cmp_string("leven", target_word,db_word)
                    if target_word_is_cyrillic==True:
                        target_word_metaphone_ru = METAPHONE_RU.transform(target_word)
                        db_word_metaphone_ru = METAPHONE_RU.transform(db_word)
                        metaphone_ru_score=cmp_string("leven", target_word_metaphone_ru,db_word_metaphone_ru)
                    else:
                        target_word_metaphone_eng = METAPHONE_ENG.encode(target_word)
                        db_word_metaphone_eng = METAPHONE_ENG.encode(db_word)
                        metaphone_en_score = cmp_string("leven", target_word_metaphone_eng,db_word_metaphone_eng)
                else:
                    if target_word_is_cyrillic: # if target word is cyrillic and db word is not cyrillic
                        leven_score1=cmp_string("leven", translit(target_word,"ru",reversed=True),db_word)
                        leven_score2=cmp_string("leven", target_word,translit(db_word,"ru"))
                        leven_score=max(leven_score1,leven_score2)

                        target_word_metaphone_ru = METAPHONE_RU.transform(target_word)
                        db_word_metaphone_ru = METAPHONE_RU.transform(translit(db_word,"ru"))
                        metaphone_ru_score=cmp_string("leven", target_word_metaphone_ru,db_word_metaphone_ru)
                        # if metaphone_ru_score>70:
                        #     print("====")
                        #     print(target_word_metaphone_ru)
                        #     print(db_word)
                        #     print(db_word_metaphone_ru)
                        #     print("====")

                    else:   # if target word is not cyrillic and db word is cyrillic
                        leven_score1=cmp_string("leven", translit(target_word,"ru"),db_word)
                        leven_score2=cmp_string("leven", target_word,translit(db_word,"ru",reversed=True))
                        leven_score=max(leven_score1,leven_score2)
                        target_word_metaphone_eng = METAPHONE_ENG.encode(target_word)
                        db_word_metaphone_eng = METAPHONE_ENG.encode(translit(db_word,"ru",reversed=True))
                        metaphone_en_score=cmp_string("leven", target_word_metaphone_eng,db_word_metaphone_eng)
                # if key == 648896 or key == "648896":
                #     print(metaphone_en_score,metaphone_ru_score,leven_score)
                if metaphone_en_score >= 70 or metaphone_ru_score >= 70 or leven_score >= 70:
                    score = metaphone_en_score/2 + metaphone_ru_score/2 + leven_score
                    relevant.append((key,score))
                # print(data)
            for el in relevant:
                image_id, score = el
                score/=len(relevant)
                if image_id in similar:
                    similar[image_id] += score
                else:
                    similar[image_id] = score
    # print(similar)
    similar = [{"image_id":key, "score":similar[key]} for key in similar]
    similar.sort(key=lambda x: x["score"], reverse=True)
    # print(similar)
    if k:
        return similar[:k]
    if distance_threshold:
        return [x for x in similar if x["score"] > distance_threshold]
    return similar


app = FastAPI()
@app.get("/")
async def read_root():
    return {"Hello": "World"}


@app.post("/calculate_text_features")
async def calculate_text_features_handler(image: bytes = File(...), image_id: str = Form(...)):
    try:
        ocr_text_arr = get_ocr_text(image)
        if len(ocr_text_arr) == 0:
            return {"error":"not text detected"}
        IMG_ID_TXT_ARR[image_id]=ocr_text_arr
        add_descriptor(int(image_id),json.dumps(ocr_text_arr,ensure_ascii=False,cls=MyEncoder))
        return Response(status_code=status.HTTP_200_OK)
    except:
        raise HTTPException(status_code=500, detail="Can't calculate text features")


class Item_image_id(BaseModel):
    image_id: int
    k: Union[str,int,None] = None
    distance_threshold: Union[str,float,None] = None

@app.post("/text_get_similar_images_by_id")
async def text_get_similar_images_by_id_handler(item: Item_image_id):
    try:
        k=item.k
        distance_threshold=item.distance_threshold
        if k:
            k = int(k)
        if distance_threshold:
            distance_threshold = float(distance_threshold)
        if (k is None) == (distance_threshold is None):
            raise HTTPException(status_code=500, detail="both k and distance_threshold present")

        ocr_text_arr = IMG_ID_TXT_ARR[str(item.image_id)]
        similar = text_find_similar(ocr_text_arr, k, distance_threshold)
        return similar
    except:
        raise HTTPException(status_code=500, detail="Error in text_get_similar_images_by_id_handler")


@app.post("/text_get_similar_images_by_image_buffer")
async def text_get_similar_images_by_image_buffer_handler(image: bytes = File(...), k: Optional[str] = Form(None), distance_threshold: Optional[str] = Form(None)):
    try:
        if k:
            k = int(k)
        if distance_threshold:
            distance_threshold = float(distance_threshold)

        if (k is None) == (distance_threshold is None):
            raise HTTPException(status_code=500, detail="both k and distance_threshold present")
        ocr_text_arr = get_ocr_text(image)
        print(convert_to_words_arr(ocr_text_arr))
        if len(ocr_text_arr) == 0:
            return {"error":"not text detected"}
        # return []
        similar = text_find_similar(ocr_text_arr, k, distance_threshold)
        return similar
    except:
        raise HTTPException(status_code=500, detail="Error in text_get_similar_images_by_image_buffer_handler")


@app.post("/delete_text_features")
async def delete_text_features_handler(item: Item_image_id):
    try:
        del IMG_ID_TXT_ARR[item.image_id]
        delete_descriptor_by_id(item.image_id)
        return Response(status_code=status.HTTP_200_OK)
    except:
        raise HTTPException(status_code=500, detail="Can't delete text features")
    

print(__name__)

if __name__ == 'text_web':
    create_table()
    # sync_db()
    init_index()
