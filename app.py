from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
from database import get_db, init_db

app = Flask(__name__)
app.secret_key = "college-auditorium-local-secret-key"

init_db()


def logged_in():
    return "user_id" in session


def admin_logged_in():
    return logged_in() and session.get("role") == "admin"


def render(name, **kwargs):
    return render_template(
        name,
        name=session.get("name", ""),
        role=session.get("role", ""),
        **kwargs
    )


def time_value(value):
    return datetime.strptime(value, "%H:%M").time()


def validate_booking_values(booking_date, start_time, end_time):
    if not booking_date or not start_time or not end_time:
        return False, "Please select date, start time and end time."

    try:
        selected_date = datetime.strptime(booking_date, "%Y-%m-%d").date()
        start = time_value(start_time)
        end = time_value(end_time)
    except ValueError:
        return False, "Invalid date or time."

    if selected_date < date.today():
        return False, "You cannot book a previous date."

    opening = time_value("09:00")
    closing = time_value("18:00")

    if start < opening:
        return False, "Auditorium opens at 9:00 AM."
    if end > closing:
        return False, "Auditorium closes at 6:00 PM."
    if start >= end:
        return False, "End time must be after start time."

    return True, ""


def find_conflict(conn, booking_date, start_time, end_time, exclude_id=None):
    query = """
        SELECT *
        FROM bookings
        WHERE booking_date = ?
          AND status IN ('pending', 'approved')
          AND start_time < ?
          AND end_time > ?
    """
    params = [booking_date, end_time, start_time]

    if exclude_id is not None:
        query += " AND id != ?"
        params.append(exclude_id)

    return conn.execute(query, params).fetchone()


@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    # Always show the login screen at the landing page.
    # A successful login then takes the user to the dashboard.

    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        selected_role = request.form.get("role", "user").strip().lower()

        if selected_role not in ("user", "admin"):
            error = "Please select either User or Admin."
        else:
            conn = get_db()
            user = conn.execute(
                """
                SELECT *
                FROM users
                WHERE username = ? AND active = 1
                """,
                (username,)
            ).fetchone()
            conn.close()

            if (
                user
                and user["role"] == selected_role
                and check_password_hash(user["password"], password)
            ):
                session.clear()
                session["user_id"] = user["id"]
                session["name"] = user["name"]
                session["role"] = user["role"]
                return redirect(url_for("dashboard"))

            error = "Invalid credentials or account type."

    return render_template("login.html", error=error)


@app.route("/dashboard")
def dashboard():
    if not logged_in():
        return redirect(url_for("login"))

    conn = get_db()

    total = conn.execute(
        "SELECT COUNT(*) AS c FROM bookings WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()["c"]

    pending = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM bookings
        WHERE user_id = ? AND status = 'pending'
        """,
        (session["user_id"],)
    ).fetchone()["c"]

    approved = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM bookings
        WHERE user_id = ? AND status = 'approved'
        """,
        (session["user_id"],)
    ).fetchone()["c"]

    upcoming = conn.execute(
        """
        SELECT *
        FROM bookings
        WHERE user_id = ?
          AND booking_date >= ?
          AND status IN ('pending', 'approved')
        ORDER BY booking_date, start_time
        LIMIT 5
        """,
        (session["user_id"], date.today().isoformat())
    ).fetchall()

    admin_pending = 0
    total_users = 0

    if admin_logged_in():
        admin_pending = conn.execute(
            "SELECT COUNT(*) AS c FROM bookings WHERE status = 'pending'"
        ).fetchone()["c"]
        total_users = conn.execute(
            "SELECT COUNT(*) AS c FROM users"
        ).fetchone()["c"]

    conn.close()

    return render(
        "dashboard.html",
        total=total,
        pending=pending,
        approved=approved,
        upcoming=upcoming,
        admin_pending=admin_pending,
        total_users=total_users
    )


@app.route("/calendar")
def calendar():
    if not logged_in():
        return redirect(url_for("login"))
    return render("calendar.html")


@app.route("/api/calendar")
def calendar_api():
    if not logged_in():
        return jsonify({"error": "Not logged in"}), 401

    conn = get_db()
    rows = conn.execute(
        """
        SELECT
            bookings.id,
            bookings.booking_date,
            bookings.start_time,
            bookings.end_time,
            bookings.event_name,
            bookings.purpose,
            bookings.participants,
            bookings.status,
            users.name AS user_name
        FROM bookings
        JOIN users ON users.id = bookings.user_id
        WHERE bookings.status IN ('pending', 'approved')
        ORDER BY bookings.booking_date, bookings.start_time
        """
    ).fetchall()
    conn.close()

    return jsonify([
        {
            "id": row["id"],
            "date": row["booking_date"],
            "start": row["start_time"],
            "end": row["end_time"],
            "event": row["event_name"],
            "purpose": row["purpose"] or "",
            "participants": row["participants"] or "",
            "status": row["status"],
            "user": row["user_name"]
        }
        for row in rows
    ])


@app.route("/book", methods=["GET", "POST"])
def book():
    if not logged_in():
        return redirect(url_for("login"))

    if request.method == "GET":
        return render("book.html", today=date.today().isoformat())

    booking_date = request.form.get("booking_date", "").strip()
    start_time = request.form.get("start_time", "").strip()
    end_time = request.form.get("end_time", "").strip()
    event_name = request.form.get("event_name", "").strip()
    purpose = request.form.get("purpose", "").strip()
    participants_text = request.form.get("participants", "").strip()

    valid, message = validate_booking_values(
        booking_date, start_time, end_time
    )

    if not valid:
        return render(
            "book.html",
            today=date.today().isoformat(),
            error=message,
            form=request.form
        )

    if not event_name:
        return render(
            "book.html",
            today=date.today().isoformat(),
            error="Please enter an event name.",
            form=request.form
        )

    participants = None
    if participants_text:
        try:
            participants = int(participants_text)
            if participants <= 0:
                raise ValueError
        except ValueError:
            return render(
                "book.html",
                today=date.today().isoformat(),
                error="Enter a valid number of participants.",
                form=request.form
            )

    conn = get_db()
    conflict = find_conflict(
        conn, booking_date, start_time, end_time
    )

    if conflict:
        conn.close()
        return render(
            "book.html",
            today=date.today().isoformat(),
            error=(
                f"Time unavailable. Existing booking is "
                f"{conflict['start_time']} - {conflict['end_time']}."
            ),
            form=request.form
        )

    conn.execute(
        """
        INSERT INTO bookings
        (
            user_id, booking_date, start_time, end_time,
            event_name, purpose, participants, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
        """,
        (
            session["user_id"],
            booking_date,
            start_time,
            end_time,
            event_name,
            purpose,
            participants
        )
    )
    conn.commit()
    conn.close()

    return render(
        "book.html",
        today=date.today().isoformat(),
        success="Booking request submitted. Waiting for admin approval."
    )


@app.route("/api/check-availability", methods=["POST"])
def check_availability():
    if not logged_in():
        return jsonify({"available": False, "message": "Please login first."}), 401

    data = request.get_json(silent=True) or {}

    booking_date = data.get("booking_date", "")
    start_time = data.get("start_time", "")
    end_time = data.get("end_time", "")

    valid, message = validate_booking_values(
        booking_date, start_time, end_time
    )

    if not valid:
        return jsonify({"available": False, "message": message})

    conn = get_db()
    conflict = find_conflict(
        conn, booking_date, start_time, end_time
    )
    conn.close()

    if conflict:
        return jsonify({
            "available": False,
            "message": (
                f"Not available. {conflict['start_time']} - "
                f"{conflict['end_time']} is already {conflict['status']}."
            )
        })

    return jsonify({
        "available": True,
        "message": "Auditorium is available for this time."
    })


@app.route("/my-bookings")
def my_bookings():
    if not logged_in():
        return redirect(url_for("login"))

    conn = get_db()
    bookings = conn.execute(
        """
        SELECT *
        FROM bookings
        WHERE user_id = ?
        ORDER BY booking_date DESC, start_time DESC
        """,
        (session["user_id"],)
    ).fetchall()
    conn.close()

    return render("my_bookings.html", bookings=bookings)


@app.route("/admin")
def admin():
    if not admin_logged_in():
        return redirect(url_for("login"))

    conn = get_db()
    users = conn.execute(
        "SELECT COUNT(*) AS c FROM users"
    ).fetchone()["c"]
    pending = conn.execute(
        "SELECT COUNT(*) AS c FROM bookings WHERE status = 'pending'"
    ).fetchone()["c"]
    approved = conn.execute(
        "SELECT COUNT(*) AS c FROM bookings WHERE status = 'approved'"
    ).fetchone()["c"]
    conn.close()

    return render(
        "admin.html",
        users=users,
        pending=pending,
        approved=approved
    )


@app.route("/admin/bookings")
def admin_bookings():
    if not admin_logged_in():
        return redirect(url_for("login"))

    conn = get_db()
    bookings = conn.execute(
        """
        SELECT
            bookings.*,
            users.name AS user_name,
            users.username AS username
        FROM bookings
        JOIN users ON users.id = bookings.user_id
        ORDER BY booking_date DESC, start_time ASC
        """
    ).fetchall()
    conn.close()

    return render("admin_bookings.html", bookings=bookings)


@app.route("/admin/bookings/<int:booking_id>/approve", methods=["POST"])
def approve_booking(booking_id):
    if not admin_logged_in():
        return redirect(url_for("login"))

    conn = get_db()
    booking = conn.execute(
        "SELECT * FROM bookings WHERE id = ?",
        (booking_id,)
    ).fetchone()

    if booking and booking["status"] == "pending":
        conflict = find_conflict(
            conn,
            booking["booking_date"],
            booking["start_time"],
            booking["end_time"],
            exclude_id=booking_id
        )

        if conflict:
            conn.close()
            return redirect(url_for("admin_bookings"))

        conn.execute(
            """
            UPDATE bookings
            SET status = 'approved'
            WHERE id = ?
            """,
            (booking_id,)
        )
        conn.commit()

    conn.close()
    return redirect(url_for("admin_bookings"))


@app.route("/admin/bookings/<int:booking_id>/reject", methods=["POST"])
def reject_booking(booking_id):
    if not admin_logged_in():
        return redirect(url_for("login"))

    conn = get_db()
    conn.execute(
        """
        UPDATE bookings
        SET status = 'rejected'
        WHERE id = ?
        """,
        (booking_id,)
    )
    conn.commit()
    conn.close()

    return redirect(url_for("admin_bookings"))


@app.route("/admin/bookings/<int:booking_id>/delete", methods=["POST"])
def delete_booking(booking_id):
    if not admin_logged_in():
        return redirect(url_for("login"))

    conn = get_db()
    conn.execute(
        "DELETE FROM bookings WHERE id = ?",
        (booking_id,)
    )
    conn.commit()
    conn.close()

    return redirect(url_for("admin_bookings"))


@app.route("/admin/users")
def manage_users():
    if not admin_logged_in():
        return redirect(url_for("login"))

    conn = get_db()
    users = conn.execute(
        """
        SELECT id, name, username, role, active
        FROM users
        ORDER BY name
        """
    ).fetchall()
    conn.close()

    return render("manage_users.html", users=users)


@app.route("/admin/users/add", methods=["POST"])
def add_user():
    if not admin_logged_in():
        return redirect(url_for("login"))

    name = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    role = request.form.get("role", "user")

    if not name or not username or not password:
        return redirect(url_for("manage_users"))

    if role not in ("user", "admin"):
        role = "user"

    conn = get_db()

    existing = conn.execute(
        "SELECT id FROM users WHERE username = ?",
        (username,)
    ).fetchone()

    if existing:
        conn.close()
        return redirect(url_for("manage_users"))

    conn.execute(
        """
        INSERT INTO users
        (name, username, password, role, active)
        VALUES (?, ?, ?, ?, 1)
        """,
        (
            name,
            username,
            generate_password_hash(password),
            role
        )
    )
    conn.commit()
    conn.close()

    return redirect(url_for("manage_users"))


@app.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
def toggle_user(user_id):
    if not admin_logged_in():
        return redirect(url_for("login"))

    if user_id == session["user_id"]:
        return redirect(url_for("manage_users"))

    conn = get_db()
    conn.execute(
        """
        UPDATE users
        SET active = CASE WHEN active = 1 THEN 0 ELSE 1 END
        WHERE id = ?
        """,
        (user_id,)
    )
    conn.commit()
    conn.close()

    return redirect(url_for("manage_users"))


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
def delete_user(user_id):
    if not admin_logged_in():
        return redirect(url_for("login"))

    if user_id == session["user_id"]:
        return redirect(url_for("manage_users"))

    conn = get_db()
    conn.execute(
        "DELETE FROM bookings WHERE user_id = ?",
        (user_id,)
    )
    conn.execute(
        "DELETE FROM users WHERE id = ?",
        (user_id,)
    )
    conn.commit()
    conn.close()

    return redirect(url_for("manage_users"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)
