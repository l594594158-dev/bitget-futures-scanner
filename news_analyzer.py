#!/usr/bin/env python3
"""
新闻分析模块 - 基于 Google News RSS
=====================================
获取美股相关新闻，分析情绪，生成信号
"""

import requests
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import logging

logger = logging.getLogger("NewsAnalyzer")

# ==================== 情绪词典 ====================
POSITIVE_WORDS = [
    # 上涨/买入相关
    'buy', 'bullish', 'outperform', 'upgrade', '上调', '买入', '看涨',
    'strong', 'growth', 'surge', 'rally', 'jump', 'gain', 'rise', 'soar',
    'beat', 'exceed', 'profit', 'earnings', 'revenue', '业绩超预期',
    'partnership', 'deal', 'contract', '合作', '订单',
    'innovation', 'breakthrough', 'launch', '发布', '新品',
    'expand', 'expansion', '扩张', '增长',
    'upgrade', 'raise', 'target', '上调目标价',
    'opportunity', 'attractive', '看好',
    'best', 'top', 'winner', '领先', '第一',
    'beat estimates', 'beat expectations', '超预期',
    'AI', 'artificial intelligence', '人工智能', 'machine learning',
    'data center', '数据中心',
    'strong demand', '需求强劲',
]

NEGATIVE_WORDS = [
    # 下跌/卖出相关
    'sell', 'bearish', 'downgrade', '下调', '卖出', '看跌',
    'weak', 'decline', 'drop', 'fall', 'plunge', 'crash', 'tumble',
    'loss', 'miss', 'below', '低于', '亏损',
    'lawsuit', 'investigation', 'probe', '调查', '诉讼',
    'recall', 'defect', 'problem', '问题', '召回',
    'layoff', 'cut', 'reduce', '裁员', '削减',
    'risk', 'warning', '警告', '风险',
    'concern', 'uncertainty', '担忧', '不确定性',
    'decline', 'falling', '下跌', '暴跌',
    'warning', 'cut', '下调目标价',
    'worst', 'bottom', 'loser', '落后', '最后',
    'miss estimates', 'miss expectations', '不及预期',
    'tariff', 'sanction', '制裁', '关税',
    'competition', 'rival', '竞争', '对手',
    'overweight', '减持', '抛售',
]

# 重大事件关键词
MAJOR_EVENT_WORDS = [
    'earnings', '财报', '业绩', 'revenue', 'profit',
    'FDA', 'approval', '批准', '监管',
    'merger', 'acquisition', '收购', '并购',
    'IPO', '上市', 'listing',
    'split', '拆股', 'dividend', '分红',
    'lawsuit', 'settlement', '诉讼', '和解',
    'investigation', 'probe', '调查',
    'CEO', 'founder', '高管', '创始人',
    'product launch', '产品发布', '发布会',
    'conference', 'conference', '会议', '大会',
]


# ==================== 新闻获取 ====================
class NewsFetcher:
    """新闻获取器 - 基于 Google News RSS"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def get_news(self, symbol: str, stock_name: str, limit: int = 10) -> List[Dict]:
        """获取新闻"""
        news_list = []
        
        # 两种搜索词
        queries = [
            f"{symbol} stock",
            f"{stock_name} stock"
        ]
        
        for query in queries:
            try:
                url = f"https://news.google.com/rss/search?q={query.replace(' ', '%20')}&hl=en-US&gl=US&ceid=US:en&start={limit}"
                resp = self.session.get(url, timeout=10)
                
                if resp.status_code == 200:
                    root = ET.fromstring(resp.content)
                    items = root.findall('.//item')
                    
                    for item in items[:limit]:
                        title = item.findtext('title', '')
                        pub_date = item.findtext('pubDate', '')
                        link = item.findtext('link', '')
                        description = item.findtext('description', '')
                        
                        # 解析日期
                        pub_time = self._parse_date(pub_date)
                        
                        news_list.append({
                            'title': title,
                            'pub_date': pub_date,
                            'pub_time': pub_time,
                            'link': link,
                            'description': description,
                            'query': query
                        })
                
                # 避免请求过快
                import time
                time.sleep(0.5)
                
            except Exception as e:
                logger.debug(f"获取 {query} 新闻失败: {e}")
        
        # 去重并按时间排序
        seen = set()
        unique_news = []
        for news in news_list:
            title = news['title']
            if title not in seen:
                seen.add(title)
                unique_news.append(news)
        
        unique_news.sort(key=lambda x: x['pub_time'] if x['pub_time'] else datetime.min, reverse=True)
        
        return unique_news[:limit]
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """解析日期"""
        if not date_str:
            return None
        
        formats = [
            '%a, %d %b %Y %H:%M:%S %Z',
            '%a, %d %b %Y %H:%M:%S',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%d %H:%M:%S',
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip()[:len(formats[0])], fmt)
            except:
                try:
                    return datetime.strptime(date_str.strip()[:25], '%a, %d %b %Y %H:%M:%S')
                except:
                    continue
        
        return None


# ==================== 情绪分析 ====================
class SentimentAnalyzer:
    """情绪分析器"""
    
    def __init__(self):
        self.positive_words = set(POSITIVE_WORDS)
        self.negative_words = set(NEGATIVE_WORDS)
        self.major_words = set(MAJOR_EVENT_WORDS)
    
    def analyze(self, news_list: List[Dict]) -> Tuple[float, List[str], List[Dict]]:
        """
        分析新闻情绪
        返回: (情绪分数, 信号列表, 事件列表)
        分数范围: -10 到 +10
        """
        if not news_list:
            return 0.0, [], []
        
        total_score = 0.0
        signals = []
        major_events = []
        now = datetime.now()
        
        for news in news_list:
            title = news.get('title', '').lower()
            description = news.get('description', '').lower()
            text = title + ' ' + description
            
            # 检查时间 - 24小时内的新闻权重更高
            pub_time = news.get('pub_time')
            time_weight = 1.0
            if pub_time:
                age = (now - pub_time).total_seconds() / 3600  # 小时
                if age < 1:
                    time_weight = 2.0  # 1小时内新闻权重加倍
                elif age < 6:
                    time_weight = 1.5  # 6小时内
                elif age > 24:
                    time_weight = 0.5  # 24小时前权重减半
            
            # 统计正负面词汇
            pos_count = sum(1 for w in self.positive_words if w in text)
            neg_count = sum(1 for w in self.negative_words if w in text)
            
            # 计算单条新闻得分
            if pos_count > neg_count:
                score = (pos_count - neg_count) * time_weight
                total_score += score
            elif neg_count > pos_count:
                score = -(neg_count - pos_count) * time_weight
                total_score += score
            
            # 检测重大事件
            for word in self.major_words:
                if word.lower() in text:
                    major_events.append({
                        'title': news.get('title', '')[:80],
                        'event': word,
                        'time': pub_time
                    })
                    break
        
        # 归一化分数到 -10 到 +10
        normalized_score = max(-10, min(10, total_score))
        
        # 生成信号
        if normalized_score >= 3:
            signals.append("新闻情绪偏多")
        elif normalized_score <= -3:
            signals.append("新闻情绪偏空")
        
        if major_events:
            signals.append(f"重大事件({len(major_events)})")
            for evt in major_events[:2]:
                signals.append(f"  - {evt['event']}: {evt['title'][:40]}...")
        
        return normalized_score, signals, major_events


# ==================== 新闻分析主类 ====================
class NewsAnalyzer:
    """新闻分析主类"""
    
    def __init__(self):
        self.fetcher = NewsFetcher()
        self.analyzer = SentimentAnalyzer()
    
    def analyze_stock(self, symbol: str, stock_name: str) -> Dict:
        """分析单只股票的新闻"""
        # 获取新闻
        news_list = self.fetcher.get_news(symbol, stock_name, limit=10)
        
        if not news_list:
            return {
                'symbol': symbol,
                'has_news': False,
                'score': 0,
                'signals': [],
                'major_events': [],
                'news_count': 0
            }
        
        # 分析情绪
        score, signals, events = self.analyzer.analyze(news_list)
        
        return {
            'symbol': symbol,
            'has_news': True,
            'score': score,
            'signals': signals,
            'major_events': events,
            'news_count': len(news_list),
            'latest_news': [
                {
                    'title': n.get('title', '')[:60],
                    'time': n.get('pub_time').strftime('%H:%M') if n.get('pub_time') else 'N/A'
                }
                for n in news_list[:3]
            ]
        }
    
    def analyze_all(self, symbols: Dict[str, Dict]) -> Dict[str, Dict]:
        """分析所有股票的新闻"""
        results = {}
        
        for symbol, config in symbols.items():
            name = config.get('name', symbol)
            
            try:
                result = self.analyze_stock(symbol, name)
                results[symbol] = result
                
                # 避免请求过快
                import time
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"分析 {symbol} 新闻失败: {e}")
                results[symbol] = {
                    'symbol': symbol,
                    'has_news': False,
                    'score': 0,
                    'signals': [],
                    'error': str(e)
                }
        
        return results


# ==================== 测试 ====================
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    
    # 测试
    symbols = {
        'TSLAONUSDT': {'name': 'Tesla'},
        'NVDAONUSDT': {'name': 'Nvidia'},
    }
    
    analyzer = NewsAnalyzer()
    
    print("=" * 60)
    print("📰 新闻分析测试")
    print("=" * 60)
    
    results = analyzer.analyze_all(symbols)
    
    for symbol, result in results.items():
        print(f"\n【{symbol}】")
        print(f"  新闻数量: {result.get('news_count', 0)}")
        print(f"  情绪分数: {result.get('score', 0):.1f}")
        print(f"  信号: {result.get('signals', [])}")
        
        if result.get('latest_news'):
            print(f"  最新新闻:")
            for news in result['latest_news'][:2]:
                print(f"    - [{news['time']}] {news['title']}...")
