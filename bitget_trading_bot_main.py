# ==================== 主交易机器人 ====================
class TradingBot:
    """主交易机器人"""
    
    def __init__(self):
        # 初始化配置
        self.config = Config()
        
        # 初始化日志
        self.logger = Logger("TradingBot", self.config.LOG_FILE)
        
        # 初始化API
        self.api = BitgetAPI(self.config)
        
        # 初始化信号生成器
        self.signals = TradingSignals(self.config)
        
        # 初始化仓位管理器
        self.pm = PositionManager(self.config, self.api, self.logger)
        
        # 初始化交易执行器
        self.executor = TradingExecutor(self.config, self.api, self.pm, self.logger)
        
        # 交易统计
        self.daily_trades = []
        self.monthly_loss = 0.0
        self.consecutive_losses = 0
        
        # 运行状态
        self.running = False
        
        self.logger.info("=" * 50)
        self.logger.info("Bitget 美股现货交易机器人 初始化完成")
        self.logger.info(f"监控标的数量: {len(self.config.SYMBOLS)}")
        self.logger.info("=" * 50)
    
    def is_market_open(self) -> bool:
        """检查美股是否开盘"""
        now = datetime.utcnow()
        # 美股交易时间: UTC 14:00-21:00 (夏令时) / 14:00-22:00 (冬令时)
        hour = now.hour
        
        # 简化判断: 周一到周五, UTC 14:00-21:00
        if now.weekday() >= 5:  # 周末
            return False
        
        if 14 <= hour < 21:
            return True
        
        return False
    
    def get_scan_interval(self) -> int:
        """根据市场状态返回扫描间隔"""
        if self.is_market_open():
            return self.config.SCAN_INTERVAL
        else:
            return self.config.SCAN_INTERVAL * 5  # 盘前盘后减少扫描频率
    
    def scan_single_symbol(self, symbol: str) -> Optional[Dict]:
        """扫描单个标的"""
        try:
            # 获取K线数据
            klines = self.api.get_klines(symbol, timeframe="1H", limit=200)
            
            if len(klines) < 60:
                self.logger.warning(f"{symbol} K线数据不足")
                return None
            
            # 转换为DataFrame
            df = pd.DataFrame(klines)
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            # 分析信号
            signal = self.signals.analyze(df, symbol)
            signal['symbol'] = symbol
            signal['price'] = klines[-1]['close']
            
            return signal
            
        except Exception as e:
            self.logger.error(f"扫描 {symbol} 失败: {str(e)}")
            return None
    
    def scan_all_symbols(self) -> List[Dict]:
        """扫描所有标的"""
        results = []
        
        self.logger.info(f"开始扫描 {len(self.config.SYMBOLS)} 个标的...")
        
        for symbol in self.config.SYMBOLS.keys():
            signal = self.scan_single_symbol(symbol)
            if signal:
                results.append(signal)
            
            # 避免请求过快
            time.sleep(0.2)
        
        self.logger.info(f"扫描完成, 获取 {len(results)} 个标的信号")
        return results
    
    def check_positions(self, signals: List[Dict]) -> List[Dict]:
        """检查持仓标的"""
        actions = []
        
        for pos_summary in self.pm.get_positions_summary():
            symbol = pos_summary['symbol']
            
            # 查找该标的的最新信号
            signal = next((s for s in signals if s['symbol'] == symbol), None)
            
            if not signal:
                continue
            
            current_price = pos_summary['current_price']
            
            # 1. 检查止损
            if self.pm.check_stop_loss(symbol, current_price):
                actions.append({
                    "action": "sell",
                    "symbol": symbol,
                    "reason": "触发止损",
                    "quantity": pos_summary['quantity']
                })
                continue
            
            # 2. 更新跟踪止损
            self.pm.update_position(symbol, current_price)
            
            # 3. 检查卖出信号
            if signal['action'] == "sell" and signal['strength'] >= 4:
                actions.append({
                    "action": "sell",
                    "symbol": symbol,
                    "reason": f"卖出信号(强度:{signal['strength']})",
                    "quantity": pos_summary['quantity']
                })
            
            # 4. RSI极端超买
            rsi = signal.get('rsi', 50)
            if rsi > 80:
                actions.append({
                    "action": "sell",
                    "symbol": symbol,
                    "reason": f"RSI极端超买({rsi:.1f})",
                    "quantity": pos_summary['quantity']
                })
        
        return actions
    
    def find_buy_opportunities(self, signals: List[Dict]) -> List[Dict]:
        """寻找买入机会"""
        opportunities = []
        
        for signal in signals:
            symbol = signal['symbol']
            
            # 跳过已有持仓的标的
            if symbol in self.pm.positions:
                continue
            
            # 只考虑买入信号
            if signal['action'] != "buy":
                continue
            
            # 强度至少为4
            if signal['strength'] < 4:
                continue
            
            opportunities.append(signal)
        
        # 按强度排序
        opportunities.sort(key=lambda x: x['strength'], reverse=True)
        
        return opportunities
    
    def execute_actions(self, actions: List[Dict]):
        """执行交易动作"""
        for action in actions:
            symbol = action['symbol']
            action_type = action['action']
            
            if action_type == "buy":
                self.executor.execute_buy(symbol, action)
            elif action_type == "sell":
                self.executor.execute_sell(
                    symbol, 
                    action['quantity'], 
                    action.get('reason', '未知原因')
                )
            
            # 避免操作过快
            time.sleep(1)
    
    def log_status(self, signals: List[Dict]):
        """记录状态日志"""
        positions = self.pm.get_positions_summary()
        
        self.logger.info("=" * 50)
        self.logger.info(f"📊 状态报告 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info(f"账户余额: {self.pm.get_account_balance():.2f} USDT")
        self.logger.info(f"持仓数量: {len(positions)}")
        
        if positions:
            total_profit = sum(p['profit_percent'] for p in positions)
            self.logger.info(f"持仓总盈亏: {total_profit:.2f}%")
            
            for pos in positions:
                self.logger.info(
                    f"  {pos['symbol']}: "
                    f"数量={pos['quantity']:.4f}, "
                    f"入场={pos['entry_price']:.4f}, "
                    f"当前={pos['current_price']:.4f}, "
                    f"盈亏={pos['profit_percent']:.2f}%"
                )
        
        # 买入信号汇总
        buy_signals = [s for s in signals if s['action'] == 'buy' and s['strength'] >= 4]
        if buy_signals:
            self.logger.info(f"🟢 买入信号: {len(buy_signals)} 个")
            for s in buy_signals[:3]:  # 只显示前3个
                self.logger.info(f"  {s['symbol']}: 强度={s['strength']}, RSI={s.get('rsi', 0):.1f}")
        
        # 卖出信号汇总
        sell_signals = [s for s in signals if s['action'] == 'sell' and s['strength'] >= 4]
        if sell_signals:
            self.logger.info(f"🔴 卖出信号: {len(sell_signals)} 个")
            for s in sell_signals[:3]:
                self.logger.info(f"  {s['symbol']}: 强度={s['strength']}, RSI={s.get('rsi', 0):.1f}")
        
        self.logger.info("=" * 50)
    
    def run_once(self):
        """执行一次扫描循环"""
        try:
            # 1. 扫描所有标的
            signals = self.scan_all_symbols()
            
            if not signals:
                self.logger.warning("未获取到任何信号")
                return
            
            # 2. 检查持仓
            position_actions = self.check_positions(signals)
            if position_actions:
                self.logger.info(f"持仓触发操作: {len(position_actions)} 个")
                self.execute_actions(position_actions)
            
            # 3. 寻找买入机会
            buy_opportunities = self.find_buy_opportunities(signals)
            if buy_opportunities:
                # 最多买入1个标的
                best = buy_opportunities[0]
                self.logger.info(f"最佳买入机会: {best['symbol']} 强度={best['strength']}")
                
                # 风险检查
                balance = self.pm.get_account_balance()
                if balance < 100:
                    self.logger.warning("余额过低, 不执行买入")
                else:
                    self.execute_actions([{
                        "action": "buy",
                        "symbol": best['symbol'],
                        "reason": f"买入信号(强度:{best['strength']})"
                    }])
            
            # 4. 记录状态
            self.log_status(signals)
            
        except Exception as e:
            self.logger.error(f"扫描循环异常: {str(e)}")
    
    def run(self):
        """运行交易机器人"""
        self.running = True
        self.logger.info("🚀 交易机器人开始运行...")
        
        while self.running:
            try:
                # 检查是否在交易时间
                if not self.is_market_open():
                    self.logger.info("⏰ 当前非美股交易时间, 进入低频监控模式")
                
                # 执行一次扫描
                self.run_once()
                
                # 等待下次扫描
                interval = self.get_scan_interval()
                self.logger.info(f"⏳ 下次扫描等待 {interval} 秒...")
                
                for _ in range(interval):
                    if not self.running:
                        break
                    time.sleep(1)
                    
            except KeyboardInterrupt:
                self.logger.info("收到停止信号...")
                self.running = False
            except Exception as e:
                self.logger.error(f"运行异常: {str(e)}")
                time.sleep(60)
        
        self.logger.info("交易机器人已停止")
    
    def stop(self):
        """停止交易机器人"""
        self.running = False


# ==================== 定时任务模式 ====================
class TradingTask:
    """定时交易任务"""
    
    def __init__(self):
        self.config = Config()
        self.logger = Logger("TradingTask", self.config.LOG_FILE)
        self.api = BitgetAPI(self.config)
    
    def run_market_scan(self):
        """盘前/盘后扫描"""
        self.logger.info("📋 执行定时扫描任务...")
        
        bot = TradingBot()
        bot.run_once()
        
        self.logger.info("✅ 定时扫描任务完成")
    
    def run_scheduled_tasks(self):
        """运行定时任务"""
        import schedule
        
        # 每天美股开盘前扫描 (北京时间 22:00 = UTC 14:00)
        schedule.every().day.at("22:00").do(self.run_market_scan)
        
        # 每天美股盘中扫描 (北京时间 02:00 = UTC 18:00)
        schedule.every().day.at("02:00").do(self.run_market_scan)
        
        # 每天美股收盘后扫描 (北京时间 09:00 = UTC 01:00)
        schedule.every().day.at("09:00").do(self.run_market_scan)
        
        self.logger.info("⏰ 定时任务已设置:")
        self.logger.info("  - 22:00 (美股开盘前)")
        self.logger.info("  - 02:00 (美股盘中)")
        self.logger.info("  - 09:00 (美股收盘后)")
        
        while True:
            schedule.run_pending()
            time.sleep(60)


# ==================== CLI 入口 ====================
def main():
    """主入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Bitget 美股现货交易机器人")
    parser.add_argument("--mode", choices=["live", "scan", "schedule"], 
                       default="scan", help="运行模式")
    parser.add_argument("--symbol", type=str, help="指定交易标的")
    
    args = parser.parse_args()
    
    if args.mode == "live":
        # 实时运行模式
        bot = TradingBot()
        bot.run()
        
    elif args.mode == "scan":
        # 单次扫描模式
        bot = TradingBot()
        bot.run_once()
        
    elif args.mode == "schedule":
        # 定时任务模式
        task = TradingTask()
        task.run_scheduled_tasks()


if __name__ == "__main__":
    main()
