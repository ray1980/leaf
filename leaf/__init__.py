"""
Leaf 框架初始化文件:
    api - API 支持
    core - 核心模块
    plugins - 插件模块
    payments - 支付模块
    modules - 运行时实例保存器

    init - 框架初始化函数
"""

import atexit as _atexit
from typing import Optional as _Optional
from typing import NoReturn as _NoReturn

from flask import Flask as _Flask

from . import api
from . import core
from . import rbac
from . import weixin
from . import selling
from . import plugins
from . import payments


modules = core.modules


class Init:
    """
    初始化 Leaf 框架资源的函数:
        kernel - 核心部分初始化函数 (第一个运行&仅一次)
        server - 服务器部分初始化函数
        logging - 覆盖错误与日志记录相关设置
        plugins - 插件部分的初始化函数
        weixin - 微信模块初始化函数
        wxpay - 微信支付模块初始化函数
        database - 连接池服务初始化函数
    """

    def __init__(self, _modules: _Optional[core.algorithm.AttrDict] = None):
        """
        初始化模块初始化函数:
            首先运行核心初始化
        """
        if _modules is None:
            _modules = modules

        # 给全局 modules 赋值
        core.modules = _modules

        # 核心初始化
        self.__modules = _modules
        self.__kernel_initialized = False

    def kernel(self) -> _NoReturn:
        """
        初始化:
            生成事件管理器
            生成任务计划调度模块
            注册核心模块 Events 中的错误信息
            添加退出 atexit 事件项目
        """

        if self.__kernel_initialized:
            return

        # 保存错误日志的基础信息 - 默认配置
        self.__modules.error = core.algorithm.AttrDict()
        self.__modules.error.messenger = core.error.Messenger()

        # 生成事件管理器与任务计划调度
        self.__modules.events = core.events.Manager()
        self.__modules.schedules = core.schedule.Manager()

        # 注册 Events 中的错误信息
        messenger: core.error.Messenger = self.__modules.error.messenger
        messenger.register(core.events.EventNotFound)
        messenger.register(core.events.InvalidEventName)
        messenger.register(core.events.InvalidRootName)
        messenger.register(core.events.ReachedMaxReg)

        # 添加 leaf.exit 事件项目
        atexit = core.events.Event("leaf.exit", ((), {}), "在 Leaf 框架退出时执行")
        self.__modules.events.add(atexit)

        # 在 atexit 中注册退出函数
        _atexit.register(
            lambda: self.__modules.events.event("leaf.exit").notify())
        self.__kernel_initialized = True

    def plugins(self, conf: core.algorithm.StaticDict) -> plugins.Manager:
        """
        插件部分初始化:
            生成插件管理器
            注册初始化部分的错误信息
            扫描所有的插件目录并尝试载入
            注册插件蓝图
            注册框架退出事件时的所有插件清理函数
        """

        # 生成插件管理器
        if conf.directory is None:
            self.__modules.plugins = plugins.Manager(plugins.current)
        else:
            self.__modules.plugins = plugins.Manager(conf.directory)

        # 注册 Plugins 模块中的错误消息
        messenger: core.error.Messenger = self.__modules.error.messenger
        messenger.register(plugins.error.PluginImportError)
        messenger.register(plugins.error.PluginNotFound)
        messenger.register(plugins.error.PluginInitError)
        messenger.register(plugins.error.PluginRuntimeError)

        # 扫描所有并载入模块
        manager: plugins.Manager = self.__modules.plugins
        manager.scan(conf.autorun)

        # 注册插件蓝图
        server: _Flask = self.__modules.server
        from .views.plugins import plugins as _plugins
        server.register_blueprint(_plugins, url_prefix="/plugins")

        # 注册所有插件停止函数
        exiting: core.events.Event = self.__modules.events.event("leaf.exit")
        exiting.hook(self.__modules.plugins.stopall)

        return manager

    def wxpay(self, conf: core.algorithm.StaticDict) -> payments.wxpay.payment:
        """
        微信支付模块初始化:
            初始化支付模块
            注册微信支付蓝图
        """
        wxpay = payments.wxpay
        self.__modules.payments = core.algorithm.AttrDict()
        self.__modules.payments.wxpay = core.algorithm.AttrDict()

        # 初始化支付实例
        jsapi = payments.wxpay.payment(
            conf.appid, conf.mchid, conf.apikey,
            conf.callbacks, conf.cert, wxpay.methods.jsapi)
        native = payments.wxpay.payment(
            conf.appid, conf.mchid, conf.apikey,
            conf.callbacks, conf.cert, wxpay.methods.native)
        inapp = payments.wxpay.payment(
            conf.appid, conf.mchid, conf.apikey,
            conf.callbacks, conf.cert, wxpay.methods.inapp)

        self.__modules.payments.wxpay.jsapi = jsapi
        self.__modules.payments.wxpay.native = native
        self.__modules.payments.wxpay.inapp = inapp

        # 初始化加密实例
        signature = wxpay.signature(conf.apikey)
        self.__modules.payments.wxpay.signature = signature

        # 注册蓝图
        server: _Flask = self.__modules.server
        from .views.wxpay import wxpay as _wxpay
        server.register_blueprint(_wxpay, url_prefix="/wxpay")

        return jsapi

    def weixin(self, conf: core.algorithm.StaticDict) -> weixin.reply.Message:
        """
        微信模块初始化:
            生成微信加密套件
            注册微信加密套件
            注册微信消息套件
            注册微信蓝图
        """
        # 微信加密套件
        encryptor = weixin.Encrypt(conf.aeskey, conf.appid, conf.token)
        self.__modules.weixin = core.algorithm.AttrDict()
        self.__modules.weixin.encrypt = encryptor

        # 微信回复套件
        message = weixin.reply.Message(encryptor)
        event = weixin.reply.Event(encryptor)
        self.__modules.weixin.message = message
        self.__modules.weixin.event = event

        # 注册微信蓝图
        from .views.weixin import weixin as _weixin
        server: _Flask = self.__modules.server
        server.register_blueprint(_weixin, url_prefix="/weixin")
        self.__modules.weixin.handler = _weixin

        return message

    def server(self) -> _Flask:
        """
        服务器初始化函数:
            创建 Flask 服务器
            替换 Flask 默认 logger
            设置服务器密钥
        """
        # 生成 Flask 应用服务器
        self.__modules.server = _Flask("leaf")
        self.__modules.server.logger = self.__modules.logging.logger
        self.__modules.server.secret_key = core.tools.encrypt.random(64)

        return self.__modules.server

    def database(self, conf: core.algorithm.StaticDict) -> core.database.Pool:
        """
        数据库连接池初始化函数
            初始化数据库连接池
            设置退出时关闭连接池
            设置数据库信息
        """
        pool = core.database.MongoDBPool(
            conf.size, conf.server, conf.port,
            conf.username, conf.password, conf.timeout)
        self.__modules.database = pool

        exiting: core.events.Event = self.__modules.events.event("leaf.exit")
        exiting.hook(pool.stop)

        return pool

    def logging(self, conf: core.algorithm.StaticDict) -> core.error.Logging:
        """
        当提供了配置信息时 - 重写错误日志的部分信息:
            logging.logger.formatter
            logging.file_handler
            loggnig.file_handler.level
            logging.console_handler.level
        """
        # 重新生成 Logger 实例
        if not conf.format is None:
            logging = self.__modules.logging = core.error.Logging(
                file=conf.rcfile, fmt=conf.format)
        else:
            logging = self.__modules.logging = core.error.Logging(
                file=conf.rcfile)

        # 配置文件记录
        file_handler = self.__modules.logging.file_handler
        file_handler.setLevel(conf.file.level)
        if not conf.file.format is None:
            file_handler.setFormatter(conf.file.format)

        # 配置 Console 记录
        console_handler = self.__modules.logging.console_handler
        console_handler.setLevel(conf.console.level)
        if not conf.console.format is None:
            console_handler.setFormatter(conf.console.format)

        # 设置全局日志级别
        self.__modules.logging.logger.setLevel(conf.level)

        # 尝试给 server 服务器更换 logger
        try:
            self.__modules.server.logger = self.__modules.logging.logger
        except KeyError as _error:
            pass

        return logging
