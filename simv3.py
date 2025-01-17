import pandas as pd
import math
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output

# Load the CSV file from the external URL
data = pd.read_csv('https://raw.githubusercontent.com/GetHorizontal/optionsdatacsv/main/Options%20Data.csv')

# Convert date column to datetime for filtering
data['date'] = pd.to_datetime(data['date'], format='%m/%d/%Y %H:%M')

# Initialize the Dash app
app = Dash(__name__)

app.layout = html.Div([
    html.Div([
        html.Div([
            html.Label('Account Balance:'),
            dcc.Input(id='account-balance-input', type='number', value=2100),
        ], style={'margin-bottom': '20px'}),

        html.Div([
            html.Label('Date:'),
            dcc.Dropdown(
                id='date-dropdown',
                options=[{'label': date.strftime('%Y-%m-%d'), 'value': date.strftime('%Y-%m-%d')} for date in
                         sorted(data['date'].dt.date.unique())],
                value=sorted(data['date'].dt.date.unique())[0].strftime('%Y-%m-%d')
            ),
        ], style={'margin-bottom': '20px'}),

        html.Div([
            html.Label('Ticker:'),
            dcc.Dropdown(id='ticker-dropdown'),
        ], style={'margin-bottom': '20px'}),

        html.Div([
            html.Label('Upper Strike (Call):'),
            dcc.Dropdown(id='upper-strike-dropdown'),
        ], style={'margin-bottom': '20px'}),

        html.Div([
            html.Label('Lower Strike (Put):'),
            dcc.Dropdown(id='lower-strike-dropdown'),
        ], style={'margin-bottom': '20px'}),

        html.Div(id='output-div'),
        html.Div(id='result-div')
    ], style={'padding': 10, 'flex': 1}),

    html.Div([
        dcc.Graph(id='price-chart', style={'height': '80vh'})
    ], style={'padding': 10, 'flex': 3}),
], style={'display': 'flex', 'flex-direction': 'column'})


@app.callback(
    [Output('ticker-dropdown', 'options'),
     Output('ticker-dropdown', 'value')],
    Input('date-dropdown', 'value')
)
def set_ticker_options(selected_date):
    filtered_data = data[data['date'].dt.strftime('%Y-%m-%d') == selected_date]
    tickers = filtered_data['Ticker'].unique()
    return [{'label': ticker, 'value': ticker} for ticker in tickers], tickers[0]


@app.callback(
    [Output('upper-strike-dropdown', 'options'),
     Output('upper-strike-dropdown', 'value'),
     Output('lower-strike-dropdown', 'options'),
     Output('lower-strike-dropdown', 'value')],
    [Input('date-dropdown', 'value'),
     Input('ticker-dropdown', 'value')]
)
def set_strike_options(selected_date, selected_ticker):
    filtered_data = data[(data['date'].dt.strftime('%Y-%m-%d') == selected_date) & (data['Ticker'] == selected_ticker)]
    upper_strikes = filtered_data[filtered_data['Side'] == 'C']['Strike'].unique()
    lower_strikes = filtered_data[filtered_data['Side'] == 'P']['Strike'].unique()
    return ([{'label': strike, 'value': strike} for strike in upper_strikes], upper_strikes[0],
            [{'label': strike, 'value': strike} for strike in lower_strikes], lower_strikes[0])


@app.callback(
    [Output('price-chart', 'figure'),
     Output('result-div', 'children')],
    [Input('account-balance-input', 'value'),
     Input('date-dropdown', 'value'),
     Input('ticker-dropdown', 'value'),
     Input('upper-strike-dropdown', 'value'),
     Input('lower-strike-dropdown', 'value')]
)
def update_chart(account_balance, selected_date, selected_ticker, upper_strike, lower_strike):
    # Filter the data based on the inputs
    filtered_data = data[(data['date'].dt.strftime('%Y-%m-%d') == selected_date) &
                         (data['Ticker'] == selected_ticker) &
                         ((data['Strike'] == upper_strike) & (data['Side'] == 'C') |
                          (data['Strike'] == lower_strike) & (data['Side'] == 'P'))]

    # Separate the call and put data
    call_data = filtered_data[filtered_data['Side'] == 'C']
    put_data = filtered_data[filtered_data['Side'] == 'P']

    # Merge the data based on date and ensure the datetime format is parsed correctly
    combined_data = pd.merge(put_data, call_data, on='date', suffixes=('_put', '_call'))

    # Ensure we only take data between 9:30 and 16:00
    combined_data = combined_data[(combined_data['date'].dt.time >= pd.to_datetime('09:30:00').time()) &
                                  (combined_data['date'].dt.time <= pd.to_datetime('16:00:00').time())]

    # Calculate the straddle price
    combined_data['straddle_price'] = (combined_data['close_put'] + combined_data['close_call']) * 100

    # Find the daily high for the straddle price
    daily_high_price = combined_data['straddle_price'].max()
    daily_high_time = combined_data.loc[combined_data['straddle_price'].idxmax(), 'date']

    # Set parameters
    entry_time = pd.to_datetime(f'{selected_date} 09:30:00')  # Convert to Timestamp for comparison
    take_profit_percentage = 1.30
    stop_loss_percentage = 0.65
    trailing_take_profit_percentage = 0.95

    # Extract the initial prices at 9:30:00
    entry_data = combined_data[combined_data['date'] == entry_time]

    initial_straddle_price = None
    exit_price = None
    exit_time = None
    max_gain_price = None
    max_gain_time = None
    result = ""

    if not entry_data.empty:
        put_price = entry_data['close_put'].values[0]
        call_price = entry_data['close_call'].values[0]
        initial_straddle_price = (put_price + call_price) * 100

        # Define gain threshold and initialize trailing stop loss
        gain_threshold = initial_straddle_price * take_profit_percentage
        trailing_stop_loss = gain_threshold * trailing_take_profit_percentage

        # Initialize monitoring variables
        trailing_high = initial_straddle_price * take_profit_percentage
        stop_loss_triggered = False
        take_profit_triggered = False

        hit_gain_threshold = pd.DataFrame()

        # Monitor the positions for take profit and stop loss
        max_gain_price = initial_straddle_price
        max_gain_time = entry_time
        for index, row in combined_data.iterrows():
            current_straddle_price = (row['close_put'] + row['close_call']) * 100

            if current_straddle_price > max_gain_price:
                max_gain_price = current_straddle_price
                max_gain_time = row['date']

            # Adjust trailing stop loss if the price exceeds the 30% gain threshold
            if current_straddle_price >= gain_threshold:
                trailing_high = max(trailing_high, current_straddle_price)
                trailing_stop_loss = trailing_high * trailing_take_profit_percentage
                if hit_gain_threshold.empty:
                    hit_gain_threshold = combined_data.iloc[[index]]

            # Check trailing take profit
            if current_straddle_price <= trailing_stop_loss and not hit_gain_threshold.empty:
                take_profit_triggered = True
                exit_price = current_straddle_price
                exit_time = row['date']
                break

            # Check stop loss after 10:00:00
            if row['date'] >= pd.to_datetime(f'{selected_date} 10:00:00'):
                if current_straddle_price <= initial_straddle_price * stop_loss_percentage:
                    stop_loss_triggered = True
                    exit_price = current_straddle_price
                    exit_time = row['date']
                    break

        # Calculate the final return
        if stop_loss_triggered or take_profit_triggered:
            cash_to_use = 0.8 * account balance
            max straddles = math.floor(cash_to_use / initial straddle price)
            initial investment = initial straddle price * max straddles
            final value = exit price * max straddles
            net return = final value - initial investment
            percent gain loss = (net return / initial investment) * 100

            # Calculate max gain based on max gain price
            max gain value = max gain price * max straddles
            max gain net return = max gain value - initial investment
            max gain percent = (max gain net return / initial investment) * 100

            # Calculate daily high gain
            daily high value = daily high price * max straddles
            daily high net return = daily high value - initial investment
            daily high percent = (daily high net return / initial investment) * 100

            result = html.Div([
                html.P(f'Net Return: ${net_return:.2f}', style={'color': 'red'}),
                html.P(f'Percentage Gain/Loss: {percent_gain_loss:.2f}%', style={'color': 'red'}),
                html.P(f'Number of Contracts: {max_straddles}', style={'color': 'black'}),
                html.P(f'Max Gain: ${max_gain_net_return:.2f}', style={'color': 'blue'}),
                html.P(f'Max Gain Percentage: {max_gain_percent:.2f}%', style={'color': 'blue'}),
                html.P(f'Daily High Gain: ${daily_high_net_return:.2f}', style={'color': 'purple'}),
                html.P(f'Daily High Percentage: {daily_high_percent:.2f}%', style={'color': 'purple'})
            ])
        else:
            result = "Neither stop-loss nor take-profit conditions were met during the trading day."

    # Create Plotly figure
    fig = go.Figure()

    # Add traces
    fig.add_trace(
        go.Scatter(x=combined_data['date'], y=combined_data['straddle_price'], mode='lines', name='Straddle Price',
                   line=dict(color='black')))
    fig.add_trace(
        go.Scatter(x=combined_data['date'], y=combined_data['close_put'] * 100, mode='lines', name='Put Option Price',
                   line=dict(color='red')))
    fig.add_trace(
        go.Scatter(x=combined_data['date'], y=combined_data['close_call'] * 100, mode='lines', name='Call Option Price',
                   line=dict(color='green')))

    # Add markers for entry and exit points with boxes above the chart
    if initial_straddle_price is not None:
        fig.add_annotation(
            x=entry_time,
            y=combined_data['straddle_price'].max(),
            text=f'Entry\n{initial_straddle_price:.2f}',
            showarrow=False,
            xshift=0,
            yshift=20,
            bgcolor="green",
            bordercolor="green",
            font=dict(color="white")
        )
        fig.add_vline(
            x=entry_time,
            line=dict(color="green", width=2, dash="dash")
        )

        if exit_price is not None:
            fig.add_annotation(
                x=exit_time,
                y=combined_data['straddle_price'].max(),
                text=f'Exit\n{exit_price:.2f}',
                showarrow=False,
                xshift=0,
                yshift=40,
                bgcolor="red",
                bordercolor="red",
                font=dict(color="white")
            )
            fig.add_vline(
                x=exit_time,
                line=dict(color="red", width=2, dash="dash")
            )

        # Mark the maximum gain point
        if max_gain_price is not None:
            fig.add_annotation(
                x=max_gain_time,
                y=combined_data['straddle_price'].max(),
                text=f'Max Gain\n{max_gain_price:.2f}',
                showarrow=False,
                xshift=0,
                yshift=60,
                bgcolor="blue",
                bordercolor="blue",
                font=dict(color="white")
            )
            fig.add_vline(
                x=max_gain_time,
                line=dict(color="blue", width=2, dash="dash")
            )

        # Mark the daily high point
        if daily_high_price is not None:
            fig.add_annotation(
                x=daily_high_time,
                y=daily_high_price,
                text=f'Daily High\n{daily_high_price:.2f}',
                showarrow=False,
                xshift=0,
                yshift=80,
                bgcolor="black",
                bordercolor="black",
                font=dict(color="white")
            )
            fig.add_vline(
                x=daily_high_time,
                line=dict(color="black", width=2, dash="dash")
            )

    # Update layout
    fig.update_layout(
        title='Straddle, Put, and Call Prices Throughout the Day',
        xaxis_title='Time',
        yaxis_title='Price',
        legend=dict(x=1, y=1.1, xanchor='right'),
        height=800
    )

    # Return the figure and result
    return fig, result


if __name__ == '__main__':
    app.run_server(debug=True)
