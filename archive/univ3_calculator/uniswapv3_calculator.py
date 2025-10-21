import math
from decimal import Decimal

class UniswapV3Calculator:
    def __init__(self, pool_day_data, pool_ticks_data, fee_tier, token0_decimal, token1_decimal, is_pair_toggled=False):
        self.pool_day_data = pool_day_data.copy()
        self.pool_ticks_data = pool_ticks_data.copy()
        self.fee_tier = fee_tier
        self.token0_decimal = token0_decimal
        self.token1_decimal = token1_decimal
        if is_pair_toggled:
            self.token0_decimal, self.token1_decimal = self.token1_decimal, self.token0_decimal
        self.is_pair_toggled = is_pair_toggled
        
        # Q96 for precise calculations
        self.Q96 = Decimal(2) ** 96
        
        # Get current price (most recent close price)
        self.current_price = float(self.pool_day_data.iloc[0]['close'])
        print(f"Current price (token0/token1): {self.current_price:.12f}")
        print(f"Current price (token1/token0): {1/self.current_price:.2f}")
        
        # Sort ticks by tickIdx for liquidity calculation
        self.pool_ticks_data = self.pool_ticks_data.sort_values('tickIdx')
    
    def expand_decimals(self, n, exp):
        """Expand decimals"""
        return Decimal(str(n)) * (Decimal(10) ** exp)
    
    def mul_div(self, a, b, multiplier):
        """Multiply and divide"""
        return (Decimal(str(a)) * Decimal(str(b))) / Decimal(str(multiplier))
    
    def get_sqrt_price_x96(self, price):
        """Get sqrt price x96"""
        token0 = self.expand_decimals(price, self.token0_decimal)
        token1 = self.expand_decimals(1, self.token1_decimal)
        
        sqrt_ratio = (token0 / token1).sqrt()
        return sqrt_ratio * self.Q96
    
    def get_liquidity_for_amount0(self, sqrt_ratio_a_x96, sqrt_ratio_b_x96, amount0):
        """Get liquidity for amount0"""
        intermediate = self.mul_div(sqrt_ratio_b_x96, sqrt_ratio_a_x96, self.Q96)
        return self.mul_div(amount0, intermediate, sqrt_ratio_b_x96 - sqrt_ratio_a_x96)
    
    def get_liquidity_for_amount1(self, sqrt_ratio_a_x96, sqrt_ratio_b_x96, amount1):
        """Get liquidity for amount1"""
        return self.mul_div(amount1, self.Q96, sqrt_ratio_b_x96 - sqrt_ratio_a_x96)
    
    def calculate_position_liquidity(self, amount0, amount1, price_lower, price_upper, current_price):
        """Calculate position liquidity deltaL"""
        token0_decimal = self.token0_decimal
        token1_decimal = self.token1_decimal
        
        P = current_price
        Pl = price_lower
        Pu = price_upper
        
        amt0 = self.expand_decimals(amount0, self.token1_decimal)
        amt1 = self.expand_decimals(amount1, self.token0_decimal)
        
        sqrt_ratio_x96 = self.get_sqrt_price_x96(P)
        sqrt_ratio_a_x96 = self.get_sqrt_price_x96(Pl)
        sqrt_ratio_b_x96 = self.get_sqrt_price_x96(Pu)
        
        if sqrt_ratio_x96 <= sqrt_ratio_a_x96:
            liquidity = self.get_liquidity_for_amount0(sqrt_ratio_a_x96, sqrt_ratio_b_x96, amt0)
        elif sqrt_ratio_x96 < sqrt_ratio_b_x96:
            liquidity0 = self.get_liquidity_for_amount0(sqrt_ratio_x96, sqrt_ratio_b_x96, amt0)
            liquidity1 = self.get_liquidity_for_amount1(sqrt_ratio_a_x96, sqrt_ratio_x96, amt1)
            liquidity = min(liquidity0, liquidity1)
        else:
            liquidity = self.get_liquidity_for_amount1(sqrt_ratio_a_x96, sqrt_ratio_b_x96, amt1)
        
        print(f"deltaL: {liquidity:.2e}")
        return float(liquidity)
    
    def get_tokens_amount_from_deposit_amount_usd(self, P, Pl, Pu, price_usd_x, price_usd_y, deposit_amount_usd):
        """Calculate token amounts from deposit amount USD"""
        if self.is_pair_toggled:
            price_usd_x, price_usd_y = price_usd_y, price_usd_x
        
        sqrt_P = math.sqrt(P)
        sqrt_Pl = math.sqrt(Pl)
        sqrt_Pu = math.sqrt(Pu)
        
        denominator = (sqrt_P - sqrt_Pl) * price_usd_y + (1/sqrt_P - 1/sqrt_Pu) * price_usd_x
        delta_l = deposit_amount_usd / denominator
        
        delta_y = delta_l * (sqrt_P - sqrt_Pl)
        if delta_y * price_usd_y < 0:
            delta_y = 0
        if delta_y * price_usd_y > deposit_amount_usd:
            delta_y = deposit_amount_usd / price_usd_y
        
        delta_x = delta_l * (1/sqrt_P - 1/sqrt_Pu)
        if delta_x * price_usd_x < 0:
            delta_x = 0
        if delta_x * price_usd_x > deposit_amount_usd:
            delta_x = deposit_amount_usd / price_usd_x
        
        return delta_x, delta_y, delta_l
    
    def get_tick_from_price(self, price):
        """Convert price to tick"""
        pool_format_price = 1 / price
        
        token0 = pool_format_price * (10 ** self.token0_decimal)
        token1 = 1 * (10 ** self.token1_decimal)
        
        sqrt_price_token0 = math.sqrt(token0) * (2**96)
        sqrt_price_token1 = math.sqrt(token1) * (2**96)
        
        sqrt_price = sqrt_price_token1 / sqrt_price_token0
        tick = math.log(sqrt_price) / math.log(math.sqrt(1.0001))

        if self.is_pair_toggled:
            tick = -tick
        
        return int(tick)
    
    def get_volume_24h_avg(self, days=7):
        """Calculate average 24h volume"""
        if len(self.pool_day_data) < days:
            days = len(self.pool_day_data)
        
        volume_data = self.pool_day_data.head(days)['volumeUSD'].astype(float)
        avg_volume = volume_data.mean()
        
        print(f"Average 24h volume (last {days} days): ${avg_volume:,.2f}")
        return avg_volume
    
    def get_liquidity_from_tick(self, tick):
        """Calculate cumulative liquidity from ticks"""
        liquidity = 0
        
        for i in range(len(self.pool_ticks_data) - 1):
            liquidity += float(self.pool_ticks_data.iloc[i]['liquidityNet'])
            
            lower_tick = int(self.pool_ticks_data.iloc[i]['tickIdx'])
            upper_tick = int(self.pool_ticks_data.iloc[i + 1]['tickIdx']) if i + 1 < len(self.pool_ticks_data) else float('inf')
            
            if lower_tick <= tick <= upper_tick:
                break
        
        return liquidity
    
    def estimate_fee(self, liquidity_delta, liquidity, volume_24h):
        """Estimate fee using uniswap whitepaper formula"""
        liquidity_percentage = liquidity_delta / (liquidity + liquidity_delta)
        return self.fee_tier * volume_24h * liquidity_percentage