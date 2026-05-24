const BASE_URL = "http://localhost:8000";

function getAuthHeaders() {
    const token = localStorage.getItem("token");

    return {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
    };
}

export async function getTransactions(filters = {}) {
    const params = new URLSearchParams()

    if (filters.symbol) {
        params.append("symbol", filters.symbol)
    }
    if (filters.action) {
        params.append("action", filters.action)
    }
    if (filters.start_date) {
        params.append("start_date", new Date(filters.start_date).toISOString())
    }
    if (filters.end_date) {
        params.append("end_date", new Date(filters.end_date).toISOString())
    }


    const res = await fetch(`${BASE_URL}/transactions?${params.toString()}`, {
        headers: getAuthHeaders(),
    });

    if (!res.ok) {
        throw new Error("Failed to fetch transactions");
    }

    return res.json();
}

export async function createTransaction(data) {

    const res = await fetch(`${BASE_URL}/transactions`, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify(data),
    });

    if (!res.ok) {
        throw new Error("Failed to create transaction");
    }

    return res.json();
}

export async function getDashboardStats(time_span) {
    const times = new URLSearchParams()

    if (time_span) {
        times.append("current_timeperiod", time_span)
    }

    const url = times.toString()
        ? `${BASE_URL}/dashboard?${times.toString()}`
        : `${BASE_URL}/dashboard`;

    const res = await fetch(url, {
        headers: getAuthHeaders(),
    })

    if (!res.ok) {
        throw new Error(`Dashboard fetch failed: ${res.status}`);
    }

    return res.json();
}

export async function getHoldings() {

    const res = await fetch(`${BASE_URL}/holdings?}`, {
        headers: getAuthHeaders(),
    });

    if (!res.ok) {
        throw new Error(`Holdings fetch failed: ${res.status}`);
    }

    return res.json();
}

export async function getPriceHistory(symbol, type, range) {
    const res = await fetch(
        `${BASE_URL}/prices/history?symbol=${symbol}&type=${type}&range=${range}`
    );

    if (!res.ok) {
        throw new Error("Failed to load chart data");
    }

    return res.json();
}

export async function getPortfolioHistory(range) {
    const res = await fetch(
        `${BASE_URL}/portfolio/history?range=${range}`, {
            headers: getAuthHeaders()
        }
    );

    if (!res.ok) {
        throw new Error("Failed to load portfolio chart")
    }

    return res.json()
}

export async function loginAuthentication(form) {
    const formData = new URLSearchParams();

    formData.append("username", form["username"]);
    formData.append("password", form["password"]);

    const res = await fetch(
        `${BASE_URL}/auth/jwt/login`, {
            method: "POST",
            headers: {"Content-Type": "application/x-www-form-urlencoded"},
            body: formData
        }
    )

    if (!res.ok) {
        throw new Error("Invalid username or password")
    }

    const data = await res.json()

    localStorage.setItem("token", data.access_token)

    return data
}

export async function signupAuthentication(form) {
    const res = await fetch(
        `${BASE_URL}/auth/register`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                email: form.email,
                password: form.password,
                name: form.name,
            })
        }
    )

    if (!res.ok) {
        throw new Error("Signup Error")
    }

    return res.json()
}

export async function verify(params) {
    const token = params.get("token");

    const res = await fetch(
        "http://localhost:8000/auth/verify",
        {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                token: token,
            }),
        }
    );

    return res.json()
}

export async function searchStock(symbol) {
    const res = await fetch(`${BASE_URL}/assets/search/stock?asset=${symbol}`);

    if (!res.ok) {
        throw new Error("search stock error")
    }

    return res.json()
}

export async function searchCrypto(symbol) {
    const res = await fetch(`${BASE_URL}/assets/search/crypto?asset=${symbol}`);

    if (!res.ok) {
        throw new Error("search crypto error")
    }

    return res.json()
}

export async function getUser(){
    const res = await fetch(`${BASE_URL}/user`, {headers: getAuthHeaders()});

    if (!res.ok){
        throw new Error("error fetching user information")
    }

    return res.json()
}
