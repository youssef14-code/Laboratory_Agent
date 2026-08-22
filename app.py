from concurrent.futures import ThreadPoolExecutor
from venv import logger

from dotenv import load_dotenv
from griffe import logger
load_dotenv()


import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_migrate import Migrate
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from dotenv import load_dotenv
import threading
import click
from flask.cli import with_appcontext

from models.models import db, User, Laboratory, Page, LabService, Status,Platform

from software_service.laboratory_services import LaboratoryService
from software_service.homevisit_service import HomeVisitService
from software_service.inquiry_services import InquiryService
from software_service.complaint_services import ComplaintService
from software_service.user_services import UserService
from software_service.branch_services import BranchService
from software_service.client_services import ClientService
from software_service.lab_service_services import LabServiceService
from software_service.platform_services import PlatformService
from software_service.page_services import PageService
from software_service.subscripition_service import SubscriptionService
from datetime import datetime, timezone, timedelta



#from platforms.facebook_handler import FacebookHandler
#from platforms.waha_handler import WahaHandler
#from parsers.facebook import parse_facebook_message, parse_facebook_comment
#from knowledge.vector_store import ensure_vector_table

#ensure_vector_table()


# Load environment variables
load_dotenv()

# ── App & Config ──────────────────────────────────────────────────────────────
app = Flask(__name__)

secret_key = os.environ.get('SECRET_KEY')
if not secret_key:
    raise RuntimeError("SECRET_KEY must be set in environment — no default allowed in production")

db_uri = os.environ.get('SQLALCHEMY_DATABASE_URI')
if not db_uri:
    raise RuntimeError("SQLALCHEMY_DATABASE_URI must be set in environment")

app.config['SECRET_KEY'] = secret_key
app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
migrate = Migrate(app, db)

# ── Thread pool للـ webhooks بدل الـ threading.Thread المفتوحة ──────────────
WEBHOOK_MAX_WORKERS = int(os.environ.get("WEBHOOK_MAX_WORKERS", "8"))
webhook_executor = ThreadPoolExecutor(
    max_workers=WEBHOOK_MAX_WORKERS,
    thread_name_prefix="webhook_worker",
)
# ── Extensions ────────────────────────────────────────────────────────────────

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'يجب تسجيل الدخول أولاً'
login_manager.login_message_category = 'error'





@app.cli.command("create-admin")
@click.option("--username", prompt=True)
@click.option("--password", prompt=True, hide_input=True)
@with_appcontext
def create_admin(username, password):
    existing = User.query.filter_by(username=username).first()
    if existing:
        print("Admin already exists")
        return
    admin = User(username=username, password=password)
    db.session.add(admin)
    db.session.commit()
    print("Admin created successfully")


@app.cli.command("delete-admin")
@click.option("--username", prompt=True)
@with_appcontext
def delete_admin(username):
    admin = User.query.filter_by(username=username).first()
    if not admin:
        print("Admin not found")
        return
    db.session.delete(admin)
    db.session.commit()
    print("Admin deleted successfully")


@app.cli.command("list-admins")
@with_appcontext
def list_admins():
    admins = User.query.all()
    if not admins:
        print("No admins found")
        return
    for a in admins:
        print(f"ID: {a.id} | Username: {a.username}")



@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ── Context Processor (sidebar badge) ────────────────────────────────────────

@app.context_processor
def inject_globals():
    from models.models import Inquiry
    try:
        pending_count = Inquiry.query.filter_by(status=Status.PENDING).count()
    except Exception:
        pending_count = 0
    return dict(pending_inquiries_count=pending_count)


# ══════════════════════════════════════════════════════════════════════════
# Auth routes
# ══════════════════════════════════════════════════════════════════════════

# redirect root to login
@app.route('/')
def index():
    return redirect(url_for('login'))


# login page + handle login form
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        user = User.query.filter_by(username=username, password=password).first()
        if user:
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'error')
    return render_template('login.html')


# log the current user out
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ══════════════════════════════════════════════════════════════════════════
# Dashboard routes
# ══════════════════════════════════════════════════════════════════════════

# main dashboard page
@app.route('/dashboard')
@login_required
def dashboard():

    laboratory = Laboratory.query.first()

    subscription = None
    subscription_status = None
    usage_percentage = 0
    remaining_messages = 0
    alert = None

    if laboratory:

        subscription = SubscriptionService.get_subscription_by_laboratory_id(
            laboratory.id
        )

        if subscription:

            subscription_status = SubscriptionService.get_status(
                subscription
            )

            usage_percentage = SubscriptionService.usage_percentage(
                subscription
            )

            remaining_messages = SubscriptionService.messages_remaining(
                subscription
            )

            alert = SubscriptionService.get_alert(
                subscription
            )

    return render_template(
        "dashboard.html",
        subscription=subscription,
        subscription_status=subscription_status,
        usage_percentage=usage_percentage,
        remaining_messages=remaining_messages,
        alert=alert,
    )


# ══════════════════════════════════════════════════════════════════════════
# User routes
# ══════════════════════════════════════════════════════════════════════════

# list all users
@app.route('/users')
@login_required
def users():
    all_users = UserService.get_all_users()
    return render_template('users.html', users=all_users)


# create a new user
@app.route('/users/new', methods=['GET', 'POST'])
@login_required
def create_user():
    if request.method == 'POST':
        name = request.form['name']
        password = request.form['password']
        user, message = UserService.create_user(name, password)
        if user:
            flash(message, 'success')
            return redirect(url_for('users'))
        else:
            flash(message, 'danger')

    return render_template('create_user.html')


# edit an existing user
@app.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    user, message = UserService.get_user_by_id(user_id)

    if not user:
        flash(message, 'danger')
        return redirect(url_for('users'))

    if request.method == 'POST':
        name = request.form['name']
        password = request.form['password']
        updated_user, message = UserService.update_user(user_id, name, password)

        if updated_user:
            flash(message, 'success')
            return redirect(url_for('users'))
        else:
            flash(message, 'danger')

    return render_template('edit_user.html', user=user)


# ══════════════════════════════════════════════════════════════════════════
# Laboratory routes
# ══════════════════════════════════════════════════════════════════════════
# List all laboratories with search & pagination
@app.route('/laboratories')
@login_required
def list_laboratories():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '').strip() or None

    pagination, msg = LaboratoryService.get_all_laboratories(page=page, per_page=10, search=search)

    if pagination is None:
        flash(msg, 'error')
        pagination = type('Pagination', (), {
            'items': [], 'total': 0, 'pages': 0, 'page': 1,
            'has_prev': False, 'has_next': False, 'prev_num': 1, 'next_num': 1
        })()

    return render_template(
        'laboratory/list.html',
        laboratories=pagination.items,
        pagination=pagination,
        search=search
    )


# Create a new laboratory
@app.route('/laboratories/create', methods=['GET', 'POST'])
@login_required
def create_laboratory():
    if request.method == 'POST':
        lab, msg = LaboratoryService.create_laboratory(
            name=request.form.get('name'),
            info=request.form.get('info')
        )
        if lab:
            flash(msg, 'success')
            return redirect(url_for('list_laboratories'))
        flash(msg, 'error')

    return render_template('laboratory/create.html')


# Edit an existing laboratory
@app.route('/laboratories/<int:lab_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_laboratory(lab_id):
    lab, msg = LaboratoryService.get_laboratory_by_id(lab_id)
    if not lab:
        flash(msg, 'error')
        return redirect(url_for('list_laboratories'))

    if request.method == 'POST':
        updated, msg = LaboratoryService.update_laboratory(
            lab_id=lab_id,
            name=request.form.get('name'),
            info=request.form.get('info')
        )
        if updated:
            flash(msg, 'success')
            return redirect(url_for('list_laboratories'))
        flash(msg, 'error')

    return render_template('laboratory/edit.html', lab=lab)


# Delete a laboratory
@app.route('/laboratories/<int:lab_id>/delete', methods=['POST'])
@login_required
def delete_laboratory(lab_id):
    lab, msg = LaboratoryService.delete_laboratory(lab_id)
    flash(msg, 'success' if lab else 'error')
    return redirect(url_for('list_laboratories'))


# List branches of a specific laboratory
@app.route('/laboratories/<int:lab_id>/branches')
@login_required
def list_branches(lab_id):
    lab, msg = LaboratoryService.get_laboratory_by_id(lab_id)
    if not lab:
        flash(msg, 'error')
        return redirect(url_for('list_laboratories'))

    page = request.args.get('page', 1, type=int)
    pagination, msg = BranchService.get_branches_by_laboratory(lab_id, page=page, per_page=10)

    return render_template(
        'branch/list.html',
        laboratory=lab,
        branches=pagination.items,
        pagination=pagination
    )


# Create a new branch for a laboratory
@app.route('/laboratories/<int:lab_id>/branches/create', methods=['GET', 'POST'])
@login_required
def create_branch(lab_id):
    lab, msg = LaboratoryService.get_laboratory_by_id(lab_id)
    if not lab:
        flash(msg, 'error')
        return redirect(url_for('list_laboratories'))

    if request.method == 'POST':
        branch, msg = BranchService.create_branch(
            laboratory_id=lab_id,
            address=request.form.get('address'),
            phone=request.form.get('phone'),
            working_hours=request.form.get('working_hours')
        )
        if branch:
            flash(msg, 'success')
            return redirect(url_for('list_branches', lab_id=lab_id))
        flash(msg, 'error')

    return render_template('branch/create.html', laboratory=lab)


# Edit an existing branch
@app.route('/branches/<int:branch_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_branch(branch_id):
    branch, msg = BranchService.get_branch_by_id(branch_id)
    if not branch:
        flash(msg, 'error')
        return redirect(url_for('list_laboratories'))

    if request.method == 'POST':
        updated, msg = BranchService.update_branch(
            branch_id=branch_id,
            address=request.form.get('address'),
            phone=request.form.get('phone'),
            working_hours=request.form.get('working_hours')
        )
        if updated:
            flash(msg, 'success')
            return redirect(url_for('list_branches', lab_id=branch.laboratory_id))
        flash(msg, 'error')

    return render_template('branch/edit.html', branch=branch)


# Delete a branch
@app.route('/branches/<int:branch_id>/delete', methods=['POST'])
@login_required
def delete_branch(branch_id):
    branch, msg = BranchService.get_branch_by_id(branch_id)
    lab_id = branch.laboratory_id if branch else None

    deleted, msg = BranchService.delete_branch(branch_id)
    flash(msg, 'success' if deleted else 'error')

    if lab_id:
        return redirect(url_for('list_branches', lab_id=lab_id))
    return redirect(url_for('list_laboratories'))


# ══════════════════════════════════════════════════════════════════════════
# Lab (formerly "Service") routes
# ══════════════════════════════════════════════════════════════════════════

# list labs, with search + pagination
@app.route('/labs')
@login_required
def list_labs():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '').strip() or None

    pagination, msg = LabServiceService.get_all_labs(
        page=page,
        per_page=10,
        search=search
    )

    if pagination is None:
        flash(msg, 'error')
        pagination = type('Pagination', (), {
            'items': [], 'total': 0, 'pages': 0, 'page': 1,
            'has_prev': False, 'has_next': False, 'prev_num': 1, 'next_num': 1
        })()

    try:
        total_labs = LabService.query.count()
        with_specimen = LabService.query.filter(LabService.sample_type.isnot(None), LabService.sample_type != '').count()
        with_instructions = LabService.query.filter(LabService.patient_instructions.isnot(None), LabService.patient_instructions != '').count()
    except Exception:
        total_labs = len(pagination.items)
        with_specimen = 0
        with_instructions = 0

    stats = {
        'total': total_labs,
        'with_specimen': with_specimen,
        'with_instructions': with_instructions,
        'active': total_labs
    }

    return render_template(
        'labs/list.html',
        labs=pagination.items,
        pagination=pagination,
        search=search,
        stats=stats
    )


# create a new lab
@app.route('/labs/create', methods=['GET', 'POST'])
@login_required
def create_lab():
    if request.method == 'POST':
        lab, msg = LabServiceService.create_lab(
            name=request.form.get('name'),
            price=request.form.get('price'),
            sample_type=request.form.get('sample_type'),
            durations=request.form.get('durations'),
            patient_instructions=request.form.get('patient_instructions'),
        )
        if lab:
            flash(msg, 'success')
            return redirect(url_for('list_labs'))
        flash(msg, 'error')

    return render_template('labs/create.html')


# edit an existing lab
@app.route('/labs/<int:lab_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_lab(lab_id):
    lab, msg = LabServiceService.get_lab_by_id(lab_id)
    if not lab:
        flash(msg, 'error')
        return redirect(url_for('list_labs'))

    if request.method == 'POST':
        updated, msg = LabServiceService.update_lab(
            lab_id=lab_id,
            name=request.form.get('name'),
            price=request.form.get('price'),
            sample_type=request.form.get('sample_type'),
            durations=request.form.get('durations'),
            patient_instructions=request.form.get('patient_instructions'),
        )
        if updated:
            flash(msg, 'success')
            return redirect(url_for('list_labs'))
        flash(msg, 'error')

    return render_template('labs/edit.html', lab=lab)


# delete a lab
@app.route('/labs/<int:lab_id>/delete', methods=['POST'])
@login_required
def delete_lab(lab_id):
    lab, msg = LabServiceService.delete_lab(lab_id)
    flash(msg, 'success' if lab else 'error')
    return redirect(url_for('list_labs'))


# ══════════════════════════════════════════════════════════════════════════
# Knowledge pipeline routes (Labs & Bundles)
# ══════════════════════════════════════════════════════════════════════════
""" 
@app.route('/labs/<int:lab_id>/knowledge')
@login_required
def review_lab_knowledge(lab_id):
    lab, msg = LabServiceService.get_lab_by_id(lab_id)
    if not lab:
        flash(msg, 'error')
        return redirect(url_for('list_labs'))
    return render_template('knowledge/review.html', entity=lab, entity_type='lab')


@app.route('/labs/<int:lab_id>/generate-knowledge', methods=['POST'])
@login_required
def generate_lab_knowledge(lab_id):
    lab, msg = LabServiceService.get_lab_by_id(lab_id)
    if not lab:
        return jsonify({"success": False, "message": "التحليل غير موجود"})
    
    try:
        from knowledge.schemas import KnowledgeGenerationRequest, EntityType
        from knowledge.pipeline import run_pre_approval_stage
        req = KnowledgeGenerationRequest(
            name=lab.name,
            entity_type=EntityType.LAB,
            entity_id=lab.id,
            patient_instructions=lab.patient_instructions or "",
            duration=lab.durations or "غير محدد",
            price=lab.price or 0.0
        )
        res = run_pre_approval_stage(req)
        aliases_val = getattr(res, 'aliases', getattr(res, 'alias_names', []))
        data = {
            "description": res.description,
            "alias_names": ", ".join(aliases_val) if isinstance(aliases_val, list) else str(aliases_val),
            "keywords": ", ".join(res.keywords) if isinstance(res.keywords, list) else str(res.keywords),
            "search_text": res.search_text
        }
    except Exception as e:
        import traceback
        print("=== KNOWLEDGE GENERATION FAILED ===")
        traceback.print_exc()
        name = lab.name
        data = {
            "description": f"تحليل {name} الطبي للمساعدة في التشخيص الطبي وتقييم الوظائف الحيوية للمريض.",
            "alias_names": f"{name}, فحص {name}, تحليل {name}",
            "keywords": f"{name}, تحاليل طبية, عينة {lab.specimen or 'دم'}, فحوصات",
            "search_text": f"فحص وتحليل {name} - السعر: {lab.price} ج.م - العينة: {lab.specimen or 'غير محدد'} - التعليمات: {lab.patient_instructions or 'بدون صيام'}"
        }  

    return jsonify({"success": True, "data": data, "message": "تم توليد المعرفة بنجاح عبر Pipeline الذكاء الاصطناعي"})


@app.route('/labs/<int:lab_id>/approve-knowledge', methods=['POST'])
@login_required
def approve_lab_knowledge(lab_id):
    lab, msg = LabServiceService.get_lab_by_id(lab_id)
    if not lab:
        return jsonify({"success": False, "message": "التحليل غير موجود"})
    
    data = request.json or request.form
    description = data.get('description', lab.description)
    alias_names = data.get('alias_names', lab.alias_names)
    keywords = data.get('keywords', lab.keywords)
    search_text = data.get('search_text', lab.search_text)

    lab.description = description
    lab.alias_names = alias_names
    lab.keywords = keywords
    lab.search_text = search_text

    try:
        db.session.commit()
        # Trigger post approval pipeline vector store update
        try:
            from knowledge.schemas import GeneratedKnowledge, EntityType
            from knowledge.pipeline import run_post_approval_stage
            aliases_list = [a.strip() for a in alias_names.split(',') if a.strip()] if isinstance(alias_names, str) else alias_names
            keywords_list = [k.strip() for k in keywords.split(',') if k.strip()] if isinstance(keywords, str) else keywords
            gen_obj = GeneratedKnowledge(
                description=description or lab.name,
                aliases=aliases_list or [lab.name],
                keywords=keywords_list or [lab.name],
                search_text=search_text or lab.name
            )
            run_post_approval_stage(lab.id, EntityType.LAB, lab.name, gen_obj)
        except Exception as pipe_err:
          import traceback
          print("=== VECTOR STORE UPDATE FAILED ===")
          traceback.print_exc()
        return jsonify({"success": True, "message": "تم اعتماد حفظ المعرفة واعتمدت بنجاح في قاعدة البيانات وتحديث الفهرس الدلالي!"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"حدث خطأ أثناء الحفظ: {str(e)}"})


@app.route('/bundles/<int:bundle_id>/knowledge')
@login_required
def review_bundle_knowledge(bundle_id):
    bundle, msg = BundleServiceLogic.get_bundle_by_id(bundle_id)
    if not bundle:
        flash(msg, 'error')
        return redirect(url_for('list_bundles'))
    return render_template('knowledge/review.html', entity=bundle, entity_type='bundle')


@app.route('/bundles/<int:bundle_id>/generate-knowledge', methods=['POST'])
@login_required
def generate_bundle_knowledge(bundle_id):
    bundle, msg = BundleServiceLogic.get_bundle_by_id(bundle_id)
    if not bundle:
        return jsonify({"success": False, "message": "الباقة غير موجودة"})

    try:
        from knowledge.schemas import KnowledgeGenerationRequest, EntityType
        from knowledge.pipeline import run_pre_approval_stage
        req = KnowledgeGenerationRequest(
            name=bundle.name,
            entity_type=EntityType.BUNDLE,
            entity_id=bundle.id,
            patient_instructions=bundle.patient_instructions or "",
            duration="24 ساعة",
            price=bundle.price or 0.0
        )
        res = run_pre_approval_stage(req)
        aliases_val = getattr(res, 'aliases', getattr(res, 'alias_names', []))
        data = {
            "description": res.description,
            "alias_names": ", ".join(aliases_val) if isinstance(aliases_val, list) else str(aliases_val),
            "keywords": ", ".join(res.keywords) if isinstance(res.keywords, list) else str(res.keywords),
            "search_text": res.search_text
        }
    except Exception as e:
        name = bundle.name
        data = {
            "description": f"باقة {name} الفحص الطبي الشامل لفحص وتحليل الوظائف الحيوية كاملة بخصم خاص.",
            "alias_names": f"{name}, عروض {name}, فحص شامل {name}",
            "keywords": f"{name}, باقة تحاليل, فحص شامل, عروض المعمل, تحاليل",
            "search_text": f"باقة {name} الشاملة - السعر: {bundle.price} ج.م - التعليمات: {bundle.patient_instructions or 'صيام قبل الفحص'}"
        }

    return jsonify({"success": True, "data": data, "message": "تم توليد معرفة الباقة بنجاح عبر Pipeline الذكاء الاصطناعي"})


@app.route('/bundles/<int:bundle_id>/approve-knowledge', methods=['POST'])
@login_required
def approve_bundle_knowledge(bundle_id):
    bundle, msg = BundleServiceLogic.get_bundle_by_id(bundle_id)
    if not bundle:
        return jsonify({"success": False, "message": "الباقة غير موجودة"})
    
    data = request.json or request.form
    description = data.get('description', bundle.description)
    alias_names = data.get('alias_names', bundle.alias_names)
    keywords = data.get('keywords', bundle.keywords)
    search_text = data.get('search_text', bundle.search_text)

    bundle.description = description
    bundle.alias_names = alias_names
    bundle.keywords = keywords
    bundle.search_text = search_text

    try:
        db.session.commit()
        # Trigger post approval pipeline vector store update
        try:
            from knowledge.schemas import GeneratedKnowledge, EntityType
            from knowledge.pipeline import run_post_approval_stage
            aliases_list = [a.strip() for a in alias_names.split(',') if a.strip()] if isinstance(alias_names, str) else alias_names
            keywords_list = [k.strip() for k in keywords.split(',') if k.strip()] if isinstance(keywords, str) else keywords
            gen_obj = GeneratedKnowledge(
                description=description or bundle.name,
                aliases=aliases_list or [bundle.name],
                keywords=keywords_list or [bundle.name],
                search_text=search_text or bundle.name
            )
            run_post_approval_stage(bundle.id, EntityType.BUNDLE, bundle.name, gen_obj)
        except Exception as pipe_err:
            pass

        return jsonify({"success": True, "message": "تم اعتماد وتعديل معرفة الباقة بنجاح في قاعدة البيانات وتحديث الفهرس الدلالي!"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"حدث خطأ أثناء الحفظ: {str(e)}"})

 """
# ══════════════════════════════════════════════════════════════════════════
# Booking routes
# ══════════════════════════════════════════════════════════════════════════

# list bookings, with search/status filter + pagination + stats
@app.route('/bookings')
@login_required
def list_bookings():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '').strip() or None
    status = request.args.get('status', '').strip() or None

    pagination, msg = HomeVisitService.get_all_bookings(
        page=page, per_page=10, search=search, status=status
    )

    if pagination is None:
        flash(msg, 'error')
        pagination = type('Pagination', (), {
            'items': [], 'total': 0, 'pages': 0, 'page': 1,
            'has_prev': False, 'has_next': False, 'prev_num': 1, 'next_num': 1
        })()

    stats = HomeVisitService.get_stats()

    return render_template(
        'bookings/list.html',
        bookings=pagination.items,
        pagination=pagination,
        search=search,
        status_filter=status,
        stats=stats,
        all_statuses=Status,
    )


# view a single booking's details
@app.route('/bookings/<int:booking_id>')
@login_required
def view_booking(booking_id):
    booking, msg = HomeVisitService.get_visit_by_id(booking_id)
    if not booking:
        flash(msg, 'error')
        return redirect(url_for('list_bookings'))
    return render_template('bookings/detail.html', booking=booking, all_statuses=Status)


# create a new manual booking
@app.route('/bookings/new', methods=['GET', 'POST'])
@login_required
def create_booking():
    if request.method == 'POST':
        visit, msg = HomeVisitService.create_visit(
            name=request.form.get('name'),
            phone_number=request.form.get('phone_number'),
            date=request.form.get('date') or None,
            details=request.form.get('details') or None,
            comes_from='dashboard',
            address=request.form.get('address') or None,
        )
        if visit:
            flash(msg, 'success')
            return redirect(url_for('list_bookings'))
        flash(msg, 'error')

    return render_template('bookings/create.html')


# edit an existing booking
@app.route('/bookings/<int:booking_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_booking(booking_id):
    booking, msg = HomeVisitService.get_visit_by_id(booking_id)
    if not booking:
        flash(msg, 'error')
        return redirect(url_for('list_bookings'))

    if request.method == 'POST':
        updated, msg = HomeVisitService.update_visit(
            visit_id=booking_id,
            name=request.form.get('name'),
            phone_number=request.form.get('phone_number'),
            date=request.form.get('date') or None,
            details=request.form.get('details') or None,
            address=request.form.get('address') or None,
        )
        if updated:
            flash(msg, 'success')
            return redirect(url_for('list_bookings'))
        flash(msg, 'error')

    return render_template('bookings/edit.html', booking=booking)


# update a booking's status (supports both form post and AJAX/json)
@app.route('/bookings/<int:booking_id>/status', methods=['POST'])
@login_required
def update_booking_status(booking_id):
    new_status = request.form.get('status') or request.json.get('status')
    updated, msg = HomeVisitService.update_status(booking_id, new_status)
    if request.is_json:
        return jsonify(success=bool(updated), message=msg)
    flash(msg, 'success' if updated else 'error')
    return redirect(url_for('list_bookings'))


# delete a booking
@app.route('/bookings/<int:booking_id>/delete', methods=['POST'])
@login_required
def delete_booking(booking_id):
    deleted, msg = HomeVisitService.delete_visit(booking_id)
    flash(msg, 'success' if deleted else 'error')
    return redirect(url_for('list_bookings'))

# ══════════════════════════════════════════════════════════════════════════
# Inquiry (prescription) routes
# ══════════════════════════════════════════════════════════════════════════

# list inquiries, with search/status filter + pagination + stats
@app.route('/inquiries')
@login_required
def list_inquiries():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '').strip()
    status = request.args.get('status', '')

    pagination, _ = InquiryService.get_all_inquiries(
        page=page, per_page=10, search=search or None, status=status or None
    )
    stats = InquiryService.get_stats()

    return render_template(
        'inquiries/list.html',
        inquiries=pagination.items,
        pagination=pagination,
        search=search,
        status=status,
        statuses=Status,
        stats=stats,
    )


# view a single inquiry, with the list of labs available to select for it
@app.route('/inquiries/<int:inquiry_id>')
@login_required
def inquiry_detail(inquiry_id):
    result = InquiryService.get_inquiry_by_id(inquiry_id)
    if not result.success:
        flash(result.message, 'error')
        return redirect(url_for('list_inquiries'))

    pagination, _ = LabServiceService.get_all_labs(page=1, per_page=1000)
    services = pagination.items if pagination else []

    return render_template('inquiries/detail.html', inquiry=result.inquiry, services=services)


# update an inquiry's status
@app.route('/inquiries/<int:inquiry_id>/status', methods=['POST'])
@login_required
def update_inquiry_status(inquiry_id):
    new_status = request.form.get('status')
    result = InquiryService.update_status(inquiry_id, new_status)
    flash(result.message, 'success' if result.success else 'error')
    return redirect(request.referrer or url_for('list_inquiries'))


# doctor confirms the labs for a prescription; replies to the patient (via Facebook if applicable)
# doctor confirms the labs for a prescription
# TODO: إعادة تفعيل إرسال الرد عبر Facebook/WhatsApp لما يترابطوا
@app.route('/inquiries/<int:inquiry_id>/confirm', methods=['POST'])
@login_required
def confirm_inquiry(inquiry_id):
    result = InquiryService.get_inquiry_by_id(inquiry_id)
    if not result.success:
        flash(result.message, 'error')
        return redirect(url_for('list_inquiries'))

    inquiry = result.inquiry

    selected_service_ids = request.form.getlist('selected_services')
    if not selected_service_ids:
        flash('يرجى تحديد خدمة واحدة على الأقل.', 'error')
        return redirect(url_for('inquiry_detail', inquiry_id=inquiry_id))

    selected_services = LabService.query.filter(
        LabService.id.in_([int(sid) for sid in selected_service_ids])
    ).all()

    if not selected_services:
        flash('الخدمات المحددة غير صالحة.', 'error')
        return redirect(url_for('inquiry_detail', inquiry_id=inquiry_id))

    service_names = [s.name for s in selected_services]
    total_price = sum(s.price for s in selected_services)

    inquiry.services_mentioned = ", ".join(service_names)
    inquiry.status = Status.REVIEWED
    db.session.commit()

    flash(f"تمت المراجعة وحفظ البيانات محلياً. إجمالي التكلفة: {total_price} ج.م", "success")
    return redirect(url_for("inquiry_detail", inquiry_id=inquiry_id))

# delete an inquiry
@app.route('/inquiries/<int:inquiry_id>/delete', methods=['POST'])
@login_required
def delete_inquiry(inquiry_id):
    result = InquiryService.delete_inquiry(inquiry_id)
    flash(result.message, 'success' if result.success else 'error')
    return redirect(url_for('list_inquiries'))


# ══════════════════════════════════════════════════════════════════════════
# Complaint routes
# ══════════════════════════════════════════════════════════════════════════

# list complaints, with search/status filter + pagination + stats
@app.route('/complaints')
@login_required
def list_complaints():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '').strip()
    status = request.args.get('status', '')

    pagination, _ = ComplaintService.get_all_complaints(
        page=page, per_page=10, search=search or None, status=status or None
    )
    stats = ComplaintService.get_stats()

    return render_template(
        'complaints/list.html',
        complaints=pagination.items,
        pagination=pagination,
        search=search,
        status=status,
        statuses=Status,
        stats=stats,
    )


# view a single complaint's details
@app.route('/complaints/<int:complaint_id>')
@login_required
def complaint_detail(complaint_id):
    result = ComplaintService.get_complaint_by_id(complaint_id)
    if not result.success:
        flash(result.message, 'error')
        return redirect(url_for('list_complaints'))
    return render_template('complaints/detail.html', complaint=result.complaint)


# update a complaint's status
@app.route('/complaints/<int:complaint_id>/status', methods=['POST'])
@login_required
def update_complaint_status(complaint_id):
    new_status = request.form.get('status')
    result = ComplaintService.update_status(complaint_id, new_status)
    flash(result.message, 'success' if result.success else 'error')
    return redirect(request.referrer or url_for('list_complaints'))


# delete a complaint
@app.route('/complaints/<int:complaint_id>/delete', methods=['POST'])
@login_required
def delete_complaint(complaint_id):
    result = ComplaintService.delete_complaint(complaint_id)
    flash(result.message, 'success' if result.success else 'error')
    return redirect(url_for('list_complaints'))


# ══════════════════════════════════════════════════════════════════════════
# Page routes (social platform pages connected to the lab)
# ══════════════════════════════════════════════════════════════════════════

# list connected pages
@app.route('/pages')
@login_required
def list_pages():
    pages, msg = PageService.get_all_pages()
    return render_template('pages/list.html', pages=pages)


# connect a new page to a platform
@app.route('/pages/create', methods=['GET', 'POST'])
@login_required
def create_page():
    platforms, _ = PageService.get_all_platforms()

    if request.method == 'POST':
        platform_id = request.form['platform_id']
        page_id = request.form['page_id']
        token = request.form['token']
        laboratory_id = LaboratoryService.get_current_laboratory_id()

        page, msg = PageService.create_page(laboratory_id, platform_id, page_id, token)
        if page:
            flash(msg, 'success')
            return redirect(url_for('list_pages'))
        flash(msg, 'error')

    return render_template('pages/create.html', platforms=platforms)


# edit a page's token
@app.route('/pages/<int:platform_id>/<page_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_page(platform_id, page_id):
    page, msg = PageService.get_page(platform_id, page_id)
    if not page:
        flash(msg, 'error')
        return redirect(url_for('list_pages'))

    if request.method == 'POST':
        token = request.form['token']
        updated, msg = PageService.update_page_token(platform_id, page_id, token)
        if updated:
            flash(msg, 'success')
            return redirect(url_for('list_pages'))
        flash(msg, 'error')

    return render_template('pages/edit.html', page=page)


# disconnect a page
@app.route('/pages/<int:platform_id>/<page_id>/delete', methods=['POST'])
@login_required
def delete_page(platform_id, page_id):
    page, msg = PageService.delete_page(platform_id, page_id)
    flash(msg, 'success' if page else 'error')
    return redirect(url_for('list_pages'))


# ══════════════════════════════════════════════════════════════════════════
# Client routes (scoped to a page)
# ══════════════════════════════════════════════════════════════════════════

# list clients for a page, with search + pagination
@app.route('/pages/<int:platform_id>/<page_id>/clients')
@login_required
def list_clients(platform_id, page_id):
    search = request.args.get('search', '')
    page_num = request.args.get('page', 1, type=int)

    page, _ = PageService.get_page(platform_id, page_id)
    clients, msg = PageService.get_clients_for_page(
        platform_id, page_id, search=search, page_num=page_num
    )
    return render_template(
        'pages/clients.html', page=page, clients=clients, search=search
    )


# edit a client's saved summary
@app.route('/pages/<int:platform_id>/<page_id>/clients/<sender_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_client(platform_id, page_id, sender_id):
    client, msg = PageService.get_client(platform_id, page_id, sender_id)
    if not client:
        flash(msg, 'error')
        return redirect(url_for('list_clients', platform_id=platform_id, page_id=page_id))

    if request.method == 'POST':
        summary = request.form['summary']
        updated, msg = PageService.update_client_summary(platform_id, page_id, sender_id, summary)
        if updated:
            flash(msg, 'success')
            return redirect(url_for('list_clients', platform_id=platform_id, page_id=page_id))
        flash(msg, 'error')

    return render_template('pages/client_edit.html', client=client)


# delete a client
@app.route('/pages/<int:platform_id>/<page_id>/clients/<sender_id>/delete', methods=['POST'])
@login_required
def delete_client(platform_id, page_id, sender_id):
    client, msg = PageService.delete_client(platform_id, page_id, sender_id)
    flash(msg, 'success' if client else 'error')
    return redirect(url_for('list_clients', platform_id=platform_id, page_id=page_id))


# ══════════════════════════════════════════════════════════════════════════
# Platform routes (e.g. Facebook, Instagram, WhatsApp)
# ══════════════════════════════════════════════════════════════════════════

# list platforms
@app.route('/platforms')
@login_required
def list_platforms():
    platforms, msg = PlatformService.get_all_platforms()
    return render_template('platforms/list.html', platforms=platforms)


# create a new platform
@app.route('/platforms/create', methods=['GET', 'POST'])
@login_required
def create_platform():
    if request.method == 'POST':
        name = request.form['name']
        platform, msg = PlatformService.create_platform(name)
        if platform:
            flash(msg, 'success')
            return redirect(url_for('list_platforms'))
        flash(msg, 'error')

    return render_template('platforms/create.html')


# edit a platform
@app.route('/platforms/<int:platform_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_platform(platform_id):
    platform, msg = PlatformService.get_platform_by_id(platform_id)
    if not platform:
        flash(msg, 'error')
        return redirect(url_for('list_platforms'))

    if request.method == 'POST':
        name = request.form['name']
        updated, msg = PlatformService.update_platform(platform_id, name)
        if updated:
            flash(msg, 'success')
            return redirect(url_for('list_platforms'))
        flash(msg, 'error')

    return render_template('platforms/edit.html', platform=platform)




@app.route("/admin/dashbaord")
@login_required
def admin_subscription():

    laboratory = Laboratory.query.first()

    if not laboratory:
        flash("No laboratory found.", "error")
        return redirect(url_for("dashboard"))

    subscription = SubscriptionService.get_subscription_by_laboratory_id(
        laboratory.id
    )

    if not subscription:
        flash("Subscription not found.", "error")
        return redirect(url_for("dashboard"))

    return render_template(
        "subscription.html",
        subscription=subscription,
        status=SubscriptionService.get_status(subscription),
        alert=SubscriptionService.get_alert(subscription),
        remaining=SubscriptionService.messages_remaining(subscription),
        usage=SubscriptionService.usage_percentage(subscription),
    )


@app.route("/admin/subscription/renew", methods=["POST"])
@login_required
def renew_subscription():

    laboratory = Laboratory.query.first()

    subscription = SubscriptionService.get_subscription_by_laboratory_id(
        laboratory.id
    )

    months = int(request.form.get("months", 1))

    SubscriptionService.renew(
        subscription,
        months=months,
         )
    flash("Subscription renewed successfully.", "success")
    return redirect(url_for("admin_subscription"))


@app.route("/admin/subscription/reset", methods=["POST"])
@login_required
def reset_subscription_usage():

    laboratory = Laboratory.query.first()

    subscription = SubscriptionService.get_subscription_by_laboratory_id(
        laboratory.id
    )

    subscription.message_used = 0
    subscription.updated_at = datetime.now(timezone.utc)

    db.session.commit()

    flash("Usage reset successfully.", "success")

    return redirect(url_for("admin_subscription"))


@app.route("/admin/subscription/suspend", methods=["POST"])
@login_required
def suspend_subscription():

    laboratory = Laboratory.query.first()

    subscription = SubscriptionService.get_subscription_by_laboratory_id(
        laboratory.id
    )

    SubscriptionService.suspend(subscription)

    flash("Subscription suspended.", "warning")

    return redirect(url_for("admin_subscription"))


@app.route("/admin/subscription/activate", methods=["POST"])
@login_required
def activate_subscription():

    laboratory = Laboratory.query.first()

    subscription = SubscriptionService.get_subscription_by_laboratory_id(
        laboratory.id
    )

    SubscriptionService.activate(subscription)

    flash("Subscription activated.", "success")

    return redirect(url_for("admin_subscription"))  

@app.route("/admin/subscription/update-limit", methods=["POST"])
@login_required
def update_subscription_limit():

    laboratory = Laboratory.query.first()

    subscription = SubscriptionService.get_subscription_by_laboratory_id(
        laboratory.id
    )

    try:
        new_limit = int(request.form["new_limit"])

        SubscriptionService.update_limit(
            subscription,
            new_limit,
        )

        flash("Message limit updated successfully.", "success")

    except ValueError:
        flash("Invalid message limit.", "error")

    return redirect(url_for("admin_subscription"))

@app.route("/admin/subscription/update-grace", methods=["POST"])
@login_required
def update_subscription_grace():

    laboratory = Laboratory.query.first()

    subscription = SubscriptionService.get_subscription_by_laboratory_id(
        laboratory.id
    )

    try:
        new_grace = int(request.form["new_grace"])

        SubscriptionService.update_grace_limit(
            subscription,
            new_grace,
        )

        flash("Grace limit updated successfully.", "success")

    except ValueError:
        flash("Invalid grace limit.", "error")

    return redirect(url_for("admin_subscription"))


""" # ══════════════════════════════════════════════════════════════════════════
# Facebook webhook
# ══════════════════════════════════════
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN") or os.environ.get("FB_VERIFY_TOKEN")

@app.route("/webhook/facebook", methods=["GET", "POST"])
def fb_webhook():
    if request.method == "GET":
        if request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return request.args.get("hub.challenge", "")
        abort(403)

    try:
        payload = request.json or {}
        entries = payload.get("entry", [])
    except Exception:
        return "OK", 200

    def process(entries):
        with app.app_context():
            try:
                for entry in entries:
                    page_id = entry.get("id")
                    if not page_id:
                        continue

                    page = Page.query.filter_by(page_id=page_id).first()
                    if not page:
                        continue

                    handler = FacebookHandler(page)

                    for messaging in entry.get("messaging", []):

                        message = parse_facebook_message(
                            messaging=messaging,
                            page_id=page.page_id,
                            platform_id=handler.platform_id,
                            platform_name=handler.platform_name,
                        )

                        if not message:
                            continue

                        subscription = SubscriptionService.get_by_page(page)

                        allowed, _ = SubscriptionService.can_use_ai(subscription)

                        if not allowed:
                            logger.warning(
                                "Subscription limit reached for laboratory_id=%s",
                                page.laboratory_id,
                            )
                            break

                        handler.send_typing(message.sender_id)

                        reply, ticket_bytes = handler.handle(message)

                        logger.info(
                            "[FB] sender=%s has_reply=%s has_ticket=%s",
                            message.sender_id,
                            bool(reply),
                            bool(ticket_bytes),
                        )

                        if reply:
                            handler.send(message.sender_id, reply)

                        if ticket_bytes:
                            handler.send_image(
                                recipient_id=message.sender_id,
                                file_bytes=ticket_bytes,
                                filename="booking_ticket.png",
                            )

                    for change in entry.get("changes", []):
                        comment_id = parse_facebook_comment(change)
                        if not comment_id:
                            continue

                        logger.debug("[FB] comment_id=%s", comment_id)
                        handler.handle_comment(comment_id)

            except Exception as e:
                db.session.rollback()
                logger.exception("FB webhook processing error")

                from notified_center.EmailSender import send_production_alert

                send_production_alert(
                    subject="Facebook Webhook Worker Failure",
                    body_or_error=e,
                    context={
                        "entries_count": len(entries) if entries else 0
                    }
                )

            finally:
                db.session.remove()

    webhook_executor.submit(process, entries)

    return "OK", 200


@app.route("/webhook/waha", methods=["POST"])
def waha_webhook():
    logger.info("Webhook received")

    try:
        data = request.json or {}
        logger.info(data)
    except Exception:
        return "OK", 200

    payload = data.get("payload", {})
    session_name = data.get("session")

    def process(payload, session_name):
        with app.app_context():
            try:
                whatsapp_platform = Platform.query.filter_by(
                    name="whatsapp"
                ).first()

                if not whatsapp_platform:
                    logger.error("WhatsApp platform not found")
                    return

                page = Page.query.filter_by(
                    platform_id=whatsapp_platform.id
                ).first()

                if not page:
                    logger.error("WhatsApp page not found")
                    return

                logger.info(
                    "Using WhatsApp page: %s",
                    page.page_id
                )

                handler = WahaHandler(page)

                # Subscription
                subscription = SubscriptionService.get_by_page(page)

                message = handler.parse_message(
                    payload,
                    page.page_id
                )

                if not message:
                    logger.info("Message ignored")
                    return

                allowed, _ = SubscriptionService.can_use_ai(subscription)

                if not allowed:
                    logger.warning(
                        "Subscription limit reached for laboratory_id=%s",
                        page.laboratory_id,
                    )
                    return

                handler.send_typing(message.sender_id)

                # NOTE: handler.handle() -> run_agent() already deducts
                # this message + its real cost from the subscription
                # internally (see message_processor._consume_subscription).
                # Do not call SubscriptionService.consume() again here —
                # that would double-count usage for every reply sent.
                reply, ticket_bytes = handler.handle(message)

                logger.info(
                    "[WAHA] sender=%s has_reply=%s has_ticket=%s",
                    message.sender_id,
                    bool(reply),
                    bool(ticket_bytes),
                )

                if reply:
                    handler.send(
                        message.sender_id,
                        reply,
                    )

                if ticket_bytes:
                    handler.send_image(
                        recipient_id=message.sender_id,
                        file_bytes=ticket_bytes,
                        filename="booking_ticket.png",
                    )

            except Exception as e:
                db.session.rollback()
                logger.exception("WAHA webhook processing error")

                try:
                    from notified_center.EmailSender import send_production_alert

                    send_production_alert(
                        subject="WAHA Webhook Worker Failure",
                        body_or_error=e,
                        context={
                            "session_name": session_name
                        }
                    )

                except Exception:
                    logger.exception("Failed to send production alert")

            finally:
                db.session.remove()

    webhook_executor.submit(
        process,
        payload,
        session_name,
    )

    return "OK", 200 """
# ══════════════════════════════════════════════════════════════════════════
# Run
# ══════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════
# Health check
# ══════════════════════════════════════════════════════════════════════════

@app.route('/health')
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        return jsonify(status="ok"), 200
    except Exception as e:
        logger.error("Health check DB failure: %s", e)
        return jsonify(status="error", detail="db_unreachable"), 503

if __name__ == '__main__':

    app.run(debug=False)
