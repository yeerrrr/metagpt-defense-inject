#!/usr/bin/env python
# coding:utf-8
""" 
@author: nivic ybyang7
@license: Apache Licence 
@file: queue_test
@time: 2024/05/27
@contact: ybyang7@iflytek.com
@site:  
@software: PyCharm 

# code is far away from bugs with the god animal protecting
    I love animals. They taste delicious.
              ┏┓      ┏┓
            ┏┛┻━━━┛┻┓
            ┃      ☃      ┃
            ┃  ┳┛  ┗┳  ┃
            ┃      ┻      ┃
            ┗━┓      ┏━┛
                ┃      ┗━━━┓
                ┃  神兽保佑    ┣┓
                ┃　永无BUG！   ┏┛
                ┗┓┓┏━┳┓┏┛
                  ┃┫┫  ┃┫┫
                  ┗┻┛  ┗┻┛ 
"""
import queue
import threading
import time
#  Copyright (c) 2022. Lorem ipsum dolor sit amet, consectetur adipiscing elit.
#  Morbi non lorem porttitor neque feugiat blandit. Ut vitae ipsum eget quam lacinia accumsan.
#  Etiam sed turpis ac ipsum condimentum fringilla. Maecenas magna.
#  Proin dapibus sapien vel ante. Aliquam erat volutpat. Pellentesque sagittis ligula eget metus.
#  Vestibulum commodo. Ut rhoncus gravida arcu.

from queue import Queue


class Worker(threading.Thread):
    def __init__(self, queue: Queue, timeout: int):
        threading.Thread.__init__(self)
        self.queue = queue
        self.timeout = timeout
        self.start()

    def run(self) -> None:
        while True:
            try:
                content = self.queue.get(timeout=self.timeout)
            except queue.Empty as _:
                e = TimeoutError(
                    f"SparkLLMClient wait LLM api response timeout {self.timeout} seconds"
                )
                print(e)
                # continue
                continue
            except Exception as e:
                print(e)
            print(content)


class Producer(threading.Thread):
    def __init__(self, queue: Queue, timeout: int):
        threading.Thread.__init__(self)
        self.queue = queue
        self.timeout = timeout
        self.start()

    def run(self) -> None:
        while True:
            time.sleep(self.timeout)
            self.queue.put("hello")


if __name__ == '__main__':
    q = Queue()
    a = Producer(q, 11)
    b = Worker(q, 3)
