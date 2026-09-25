def register_blueprints(app):
    from src.routes import auth, main, documents, roles, employees, matrix, plans, learner, reports, admin
    for mod in (auth, main, documents, roles, employees, matrix, plans, learner, reports, admin):
        app.register_blueprint(mod.bp)

    from src.routes.helpers import status_class, fmt_dt
    app.jinja_env.filters["status_class"] = status_class
    app.jinja_env.filters["dt"] = fmt_dt
    from role_matrix.extractor import stage_index
    app.jinja_env.filters["by_stage"] = lambda mods: sorted(mods, key=lambda m: stage_index(m["stage"]))
