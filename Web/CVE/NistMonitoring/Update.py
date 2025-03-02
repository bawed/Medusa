#!/usr/bin/env python
# -*- coding: utf-8 -*-
import zipfile
import json
from Web.DatabaseHub import NistData
import urllib3
from ClassCongregation import GetTempFilePath,ErrorLog
from config import nist_update_banner
import time
import requests
from celery import shared_task

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
TempFilePath = GetTempFilePath().Result()  # 获取TMP文件路径
headers={
    "Connection": "close",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 11_0_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "dnt": "1"
}
@shared_task
def Download():#更新数据下载
    try:
        FileName="nvdcve-1.1-" + str("modified") + ".json.zip"#下载文件名
        SaveFileName="nvdcve-1.1-" + str("modified") +str(int(time.time()))+ ".json.zip"
        Url="https://nvd.nist.gov/feeds/json/cve/1.1/"+FileName
        StartingTime=time.time()
        if nist_update_banner:
            print("[ + ] 正在重新下载文件：\033[36m" + FileName+ "\033[0m")
        DownloadFile=requests.get(Url,headers=headers,  verify=False,timeout=60)
        with open(TempFilePath+SaveFileName, 'wb+') as file:
            file.write(DownloadFile.content)
        if nist_update_banner:
            print("[ - ] 成功下载文件：\033[36m" + FileName + "\033[0m 耗时：\033[34m" + str(
            time.time() - StartingTime) + "S \033[0m")
        NistUpdateProcessing(TempFilePath+SaveFileName,FileName[:-4])#调用数据处理函数，传入文件路径和提取文件名
    except Exception as e:
        Download(TempFilePath)#如果还是报错就再次循环自身
        ErrorLog().Write("Web_CVE_NistMonitoring_NistUpdata_NistUpdateDownload(def)", e)


def NistUpdateProcessing(ZipFilePath,ZipFileData):#更新数据库处理函数
    try:
        StartingTime = time.time()
        Nist=NistData()#初始化连接

        zipFile = zipfile.ZipFile(ZipFilePath, 'r')#获取下载好的数据

        ZipData = zipFile.read(ZipFileData).decode('utf-8')#读取到的byte类型进行转换到字符串类型
        ExtractData=json.loads(ZipData)["CVE_Items"]#提取需要的数据

        if len(ExtractData)==0:#判断文件是否下载错误
            Download(TempFilePath)  # 如果下载错误就重新下载
            return 0
        DataSet=[]#存放所有tuple类型数据容器
        UpdateData = []  # 存放所有需要更新的数据
        InsertData = []  # 存放所有需要插入的数据
        UpdateCount=0#更新数据计数
        InsertCount=0#插入数据计数
        for Data in ExtractData:
            VulnerabilityNumber =Data["cve"]["CVE_data_meta"]["ID"]#提取CVE编号
            VulnerabilityDescription = Data["cve"]["description"]["description_data"][0]["value"]  # 漏洞说明
            #上述两个必定存在的值，下面的参数不一定存在
            try:
                V3BaseScore=Data["impact"]["baseMetricV3"]["cvssV3"]["baseScore"]#CVSS v3版本分值
            except:
                V3BaseScore=""
            try:
                V3BaseSeverity = Data["impact"]["baseMetricV3"]["cvssV3"]["baseSeverity"]  # CVSS v3等级分类
            except:
                V3BaseSeverity=""
            try:
                V2BaseScore = Data["impact"]["baseMetricV2"]["cvssV2"]["baseScore"]  # CVSS v2版本分值
            except:
                V2BaseScore=""
            try:
                V2BaseSeverity = Data["impact"]["baseMetricV2"]["severity"]  # CVSS v2等级分类
            except:
                V2BaseSeverity=""
            try:
                LastUpDate= Data["lastModifiedDate"].partition('T')[0]  #最后修改日期
            except:
                LastUpDate=""
            try:
                ConfigurationsNodes = Data["configurations"]["nodes"]
                Vendors=[]#存放供应商
                VendorsTmp= []  # 存放未进行大小写转换的供应商数据
                Products=[]#存放产品
                ProductsTmp = []  # 存放未进行大小写转换的产品数据
                for i in ConfigurationsNodes:
                    VendorsTmp.append(i["cpe_match"][0]["cpe23Uri"].split(":")[3])#对供应商数据进行提取分割
                    ProductsTmp.append(i["cpe_match"][0]["cpe23Uri"].split(":")[4])#对产品数据进行提取分割
                for i in VendorsTmp:#对供应商数据进行处理
                    Tmp=[]#临时数据
                    for x in i.split("_"):#进行数据分割
                        Tmp.append(x.capitalize())#首字母大写化
                    Vendors.append(' '.join(Tmp))#对数据进行拼接后发送到容器
                for i in ProductsTmp:#对供产品据进行处理
                    Tmp=[]#临时数据
                    for x in i.split("_"):#进行数据分割
                        Tmp.append(x.capitalize())#首字母大写化
                    Products.append(' '.join(Tmp))#对数据进行拼接后发送到容器
            except:
                Vendors=""
                Products=""
            if len(Vendors)==0:#判断是否有数据
                Vendors=""
            if len(Products)==0:
                Products = ""
            DataSet.append((VulnerabilityNumber, V3BaseScore, V3BaseSeverity, V2BaseScore,
                            V2BaseSeverity, LastUpDate, VulnerabilityDescription, str(Vendors), str(Products), str(Data)))

        for i in DataSet:
            SearchResult=Nist.UniqueInquiry(vulnerability_number=i[0])#获取查询结果
            if SearchResult:#如果有数据
                UpdateData.append(i+(i[0],))#在后面添加上vulnerability_number值用来作为更新的key
            else:
                InsertData.append(i)

            if len(UpdateData)==500:#500写入一次数据库
                Nist.Update(UpdateData)
                UpdateCount+=500
                UpdateData.clear()#写入后清空数据库
            if len(InsertData)==500:#500写入一次数据库
                Nist.Write(InsertData)
                InsertCount += 500
                InsertData.clear()#写入后清空数据库


        #不足500的数据写入
        Nist.Update(UpdateData)
        UpdateCount+=len(UpdateData)
        UpdateData.clear()#写入后清空数据库
        Nist.Write(InsertData)
        InsertCount+=len(InsertData)
        InsertData.clear()#写入后清空数据库
        if nist_update_banner:
            print("[ ~ ] 更新文件来源：\033[36m"+ZipFilePath+"\033[0m 耗时：\033[34m" + str(time.time() - StartingTime) + "S \033[0m 更新数据：\033[32m"+str(UpdateCount)+"\033[0m条"+" 插入数据：\033[32m"+str(InsertCount)+"\033[0m条")
        zipFile.close()

    except Exception as e:
        Download(TempFilePath)#如果文件不是zip文件，就是表明可能下载错误了
        ErrorLog().Write(
            "Web_CVE_NistMonitoring_NistUpdata_NistUpdateProcessing(def)", e)
